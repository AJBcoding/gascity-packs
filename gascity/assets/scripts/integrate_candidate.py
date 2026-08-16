#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

import validate_build_artifact


@dataclass(frozen=True)
class SourceRecord:
    bead_id: str
    base_sha: str
    result_sha: str
    dependencies: tuple[str, ...]
    worktree: Path
    changed_paths: tuple[str, ...]
    summary_path: Path
    summary_hash: str


@dataclass(frozen=True)
class IntegrationManifest:
    path: Path
    workflow: dict[str, Any]
    methodology: dict[str, Any]
    producer_attempt: int
    repository: Path
    artifact_root: Path
    remote: str
    target_ref: str
    base_sha: str
    sources: tuple[SourceRecord, ...]
    verification: tuple[tuple[str, ...], ...]


class IntegrationError(Exception):
    pass


def run_git(repository: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise IntegrationError(f"git {' '.join(args)} failed: {detail}")
    return completed


def load_manifest(path: Path) -> IntegrationManifest:
    resolved_path = path.resolve(strict=True)
    artifact = validate_build_artifact.validate_artifact_text(
        resolved_path.read_text(encoding="utf-8"),
        expected_schema="gc.build.integration-manifest.v1",
    )
    front = artifact.front_matter
    integration = front["integration"]
    sources = tuple(
        SourceRecord(
            bead_id=source["bead_id"],
            base_sha=source["base_sha"],
            result_sha=source["result_sha"],
            dependencies=tuple(source["dependencies"]),
            worktree=Path(source["worktree"]),
            changed_paths=tuple(source["changed_paths"]),
            summary_path=Path(source["summary"]["path"]),
            summary_hash=source["summary"]["hash"],
        )
        for source in integration["sources"]
    )
    return IntegrationManifest(
        path=resolved_path,
        workflow=front["workflow"],
        methodology=front["methodology"],
        producer_attempt=front["producer"]["attempt"],
        repository=Path(integration["repository"]),
        artifact_root=Path(integration["artifact_root"]),
        remote=integration["remote"],
        target_ref=integration["target_ref"],
        base_sha=integration["base_sha"],
        sources=sources,
        verification=tuple(tuple(argv) for argv in integration["verification"]),
    )


def ensure_within(path: Path, root: Path, field: str) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve(strict=True)
    if resolved != resolved_root and not resolved.is_relative_to(resolved_root):
        raise IntegrationError(f"{field} must resolve within {resolved_root}")
    return resolved


def verify_manifest_provenance(manifest: IntegrationManifest, result_path: Path) -> tuple[Path, Path]:
    repository = manifest.repository.resolve(strict=True)
    repository_top = Path(run_git(repository, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if repository_top != repository:
        raise IntegrationError(f"integration.repository must be the Git top level: {repository_top}")

    artifact_root = manifest.artifact_root.resolve(strict=True)
    ensure_within(manifest.path, artifact_root, "manifest path")
    ensure_within(result_path, artifact_root, "result path")
    if result_path.exists():
        raise IntegrationError(f"result already exists: {result_path}")

    for source in manifest.sources:
        worktree = source.worktree.resolve(strict=True)
        worktree_top = Path(run_git(worktree, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
        if worktree_top != worktree:
            raise IntegrationError(f"source {source.bead_id} worktree must be a Git top level")
        if run_git(worktree, "rev-parse", "HEAD").stdout.strip() != source.result_sha:
            raise IntegrationError(f"source {source.bead_id} result_sha does not match worktree HEAD")
        if run_git(worktree, "merge-base", "--is-ancestor", source.base_sha, source.result_sha, check=False).returncode != 0:
            raise IntegrationError(f"source {source.bead_id} result_sha does not descend from base_sha")
        run_git(repository, "cat-file", "-e", f"{source.result_sha}^{{commit}}")
        summary = source.summary_path.resolve(strict=True)
        ensure_within(summary, artifact_root, f"source {source.bead_id} summary path")
        actual_hash = f"sha256:{hashlib.sha256(summary.read_bytes()).hexdigest()}"
        if actual_hash != source.summary_hash:
            raise IntegrationError(f"source {source.bead_id} summary hash does not match")

    return repository, artifact_root


def result_document(
    manifest: IntegrationManifest,
    *,
    outcome: str,
    scratch_worktree: Path,
    source_map: list[dict[str, str]],
    verification: list[dict[str, Any]],
    candidate_sha: str = "",
    tree_sha: str = "",
    conflict_paths: list[str] | None = None,
    last_clean_candidate_sha: str = "",
    failure: dict[str, str] | None = None,
) -> str:
    manifest_hash = f"sha256:{hashlib.sha256(manifest.path.read_bytes()).hexdigest()}"
    front_matter = {
        "schema": "gc.build.integration-result.v1",
        "workflow": manifest.workflow,
        "methodology": manifest.methodology,
        "producer": {
            "formula": "integrate",
            "stage": "assemble-candidate",
            "attempt": manifest.producer_attempt,
        },
        "status": "approved" if outcome == "ready" else "blocked",
        "integration": {
            "outcome": outcome,
            "manifest_path": str(manifest.path),
            "manifest_hash": manifest_hash,
            "base_sha": manifest.base_sha,
            "scratch_worktree": str(scratch_worktree),
            "source_map": source_map,
            "verification": verification,
            "conflict_paths": conflict_paths or [],
            "push_performed": False,
            "pr_opened": False,
            "target_ref_updated": False,
        },
        "trace": {
            "upstream": [{"path": str(manifest.path), "hash": manifest_hash}],
            "coverage": [],
        },
    }
    integration = front_matter["integration"]
    if candidate_sha:
        integration["candidate_sha"] = candidate_sha
    if tree_sha:
        integration["tree_sha"] = tree_sha
    if last_clean_candidate_sha:
        integration["last_clean_candidate_sha"] = last_clean_candidate_sha
    if failure:
        integration["failure"] = failure
    section_text = {
        "Outcome": outcome,
        "Candidate": (
            f"Candidate `{candidate_sha}` with tree `{tree_sha}`."
            if candidate_sha
            else f"Last clean candidate `{last_clean_candidate_sha}`."
        ),
        "Source Map": "\n".join(
            f"- `{record['bead_id']}`: `{record['source_sha']}` -> `{record['integrated_sha']}`"
            for record in source_map
        ),
        "Verification": "\n".join(
            f"- exit {record['exit_code']}: `{record['argv']}`" for record in verification
        ),
        "Conflicts": "\n".join(f"- `{path}`" for path in conflict_paths or []) or "None.",
        "Safety": "Shadow result only; no push, PR, or target-ref update was performed.",
    }
    body = "\n\n".join(f"## {name}\n\n{text}" for name, text in section_text.items())
    return f"---\n{yaml.safe_dump(front_matter, sort_keys=False).rstrip()}\n---\n\n{body}\n"


def write_result(path: Path, document: str) -> None:
    validate_build_artifact.validate_artifact_text(
        document,
        expected_schema="gc.build.integration-result.v1",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists():
        raise IntegrationError(f"temporary result already exists: {temporary}")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise IntegrationError(f"result already exists: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def assemble(manifest: IntegrationManifest, result_path: Path) -> int:
    result_path = result_path.resolve()
    repository, artifact_root = verify_manifest_provenance(manifest, result_path)

    run_git(repository, "fetch", "--no-tags", manifest.remote, manifest.target_ref)
    fetched_sha = run_git(repository, "rev-parse", "FETCH_HEAD").stdout.strip()
    if fetched_sha != manifest.base_sha:
        raise IntegrationError(
            f"manifest base_sha {manifest.base_sha} does not match fetched target {fetched_sha}"
        )

    workflow_id = str(manifest.workflow["id"])
    if re.fullmatch(r"[A-Za-z0-9._-]+", workflow_id) is None:
        raise IntegrationError("workflow.id must be safe for an artifact path")
    attempt_dir = artifact_root / "integration" / workflow_id / f"attempt-{manifest.producer_attempt}"
    if attempt_dir.exists():
        raise IntegrationError(f"integration attempt already exists: {attempt_dir}")
    attempt_dir.mkdir(parents=True)
    scratch = attempt_dir / "candidate"
    for source in manifest.sources:
        source_root = source.worktree.resolve(strict=True)
        if scratch.is_relative_to(source_root) or source_root.is_relative_to(scratch):
            raise IntegrationError(f"scratch worktree overlaps source {source.bead_id}")
    run_git(repository, "worktree", "add", "--detach", str(scratch), manifest.base_sha)

    source_by_id = {source.bead_id: source for source in manifest.sources}
    ordered_ids = validate_build_artifact.topological_source_order(
        [
            {"bead_id": source.bead_id, "dependencies": list(source.dependencies)}
            for source in manifest.sources
        ]
    )
    source_map: list[dict[str, str]] = []
    for bead_id in ordered_ids:
        source = source_by_id[bead_id]
        cherry_pick = run_git(scratch, "cherry-pick", "--no-edit", source.result_sha, check=False)
        if cherry_pick.returncode != 0:
            conflict_paths = [
                path
                for path in run_git(scratch, "diff", "--name-only", "--diff-filter=U").stdout.splitlines()
                if path
            ]
            last_clean_candidate_sha = run_git(scratch, "rev-parse", "HEAD").stdout.strip()
            run_git(scratch, "cherry-pick", "--abort")
            write_result(
                result_path,
                result_document(
                    manifest,
                    outcome="needs_rework",
                    scratch_worktree=scratch,
                    source_map=source_map,
                    verification=[],
                    conflict_paths=conflict_paths,
                    last_clean_candidate_sha=last_clean_candidate_sha,
                ),
            )
            return 1
        source_map.append(
            {
                "bead_id": bead_id,
                "source_sha": source.result_sha,
                "integrated_sha": run_git(scratch, "rev-parse", "HEAD").stdout.strip(),
            }
        )

    verification: list[dict[str, Any]] = []
    clean_env = {key: value for key, value in os.environ.items() if not key.startswith("GC_")}
    for argv in manifest.verification:
        completed = subprocess.run(
            list(argv),
            cwd=scratch,
            env=clean_env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        verification.append(
            {
                "argv": list(argv),
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
        if completed.returncode != 0:
            candidate_sha = run_git(scratch, "rev-parse", "HEAD").stdout.strip()
            tree_sha = run_git(scratch, "rev-parse", "HEAD^{tree}").stdout.strip()
            write_result(
                result_path,
                result_document(
                    manifest,
                    outcome="failed",
                    scratch_worktree=scratch,
                    source_map=source_map,
                    verification=verification,
                    candidate_sha=candidate_sha,
                    tree_sha=tree_sha,
                ),
            )
            return 1

    candidate_sha = run_git(scratch, "rev-parse", "HEAD").stdout.strip()
    tree_sha = run_git(scratch, "rev-parse", "HEAD^{tree}").stdout.strip()
    write_result(
        result_path,
        result_document(
            manifest,
            outcome="ready",
            scratch_worktree=scratch,
            source_map=source_map,
            verification=verification,
            candidate_sha=candidate_sha,
            tree_sha=tree_sha,
        ),
    )
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble a shadow integration candidate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    assemble_parser = subparsers.add_parser("assemble")
    assemble_parser.add_argument("--manifest", required=True, type=Path)
    assemble_parser.add_argument("--result", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    manifest: IntegrationManifest | None = None
    try:
        manifest = load_manifest(args.manifest)
        return assemble(manifest, args.result)
    except (
        IntegrationError,
        OSError,
        UnicodeDecodeError,
        validate_build_artifact.ValidationError,
        yaml.YAMLError,
    ) as exc:
        if manifest is not None:
            try:
                result_path = args.result.resolve()
                artifact_root = manifest.artifact_root.resolve(strict=True)
                ensure_within(result_path, artifact_root, "result path")
                workflow_id = str(manifest.workflow["id"])
                safe_workflow_id = workflow_id if re.fullmatch(r"[A-Za-z0-9._-]+", workflow_id) else "invalid-workflow"
                scratch = artifact_root / "integration" / safe_workflow_id / f"attempt-{manifest.producer_attempt}" / "candidate"
                failure_class = "provenance" if "source " in str(exc) or "base_sha" in str(exc) else "execution"
                write_result(
                    result_path,
                    result_document(
                        manifest,
                        outcome="failed",
                        scratch_worktree=scratch,
                        source_map=[],
                        verification=[],
                        failure={"class": failure_class, "message": str(exc)},
                    ),
                )
            except (
                IntegrationError,
                OSError,
                validate_build_artifact.ValidationError,
                yaml.YAMLError,
            ):
                pass
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
