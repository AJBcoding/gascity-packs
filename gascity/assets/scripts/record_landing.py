#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import validate_build_artifact


class LandingAdapterError(Exception):
    pass


def sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def require_within(path: Path, root: Path, field: str) -> Path:
    resolved = path.resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    if resolved != resolved_root and not resolved.is_relative_to(resolved_root):
        raise LandingAdapterError(f"{field} must resolve within the integration artifact root")
    return resolved


def run_git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise LandingAdapterError(f"git {args[0]} failed")
    return completed.stdout.strip()


def normalize_remote_identity(repository: Path, remote: str) -> str:
    raw = run_git(repository, "remote", "get-url", "--all", remote)
    urls = raw.splitlines()
    if len(urls) != 1 or not urls[0]:
        raise LandingAdapterError("publication remote must resolve to exactly one URL")
    value = urls[0]
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise LandingAdapterError("publication remote URL contains control characters")
    try:
        parsed = urlsplit(value)
        username = parsed.username
    except ValueError as exc:
        raise LandingAdapterError("publication remote URL is invalid") from exc
    scp_colon = value.find(":")
    scp_like = scp_colon > 0 and os.sep not in value[:scp_colon]
    if username is not None or (scp_like and "@" in value[:scp_colon]):
        raise LandingAdapterError("publication remote URL must not contain credentials")
    if parsed.scheme == "file" and parsed.hostname in (None, "", "localhost"):
        remote_path = parsed.path
    elif parsed.scheme or scp_like:
        return value
    else:
        remote_path = value
    if not os.path.isabs(remote_path):
        remote_path = os.path.join(repository, remote_path)
    return os.path.normpath(os.path.abspath(remote_path))


def load_artifact(path: Path, schema: str) -> validate_build_artifact.BuildArtifact:
    return validate_build_artifact.validate_artifact_text(
        path.read_text(encoding="utf-8"),
        expected_schema=schema,
    )


def require_source_map_matches_manifest(
    source_map: list[dict[str, Any]], manifest_sources: list[dict[str, Any]], schema_version: int
) -> None:
    manifest_by_id = {record["bead_id"]: record for record in manifest_sources}
    if len(source_map) != len(manifest_sources) or {record["bead_id"] for record in source_map} != set(manifest_by_id):
        raise LandingAdapterError("integration result source map does not match manifest sources")
    for record in source_map:
        source = manifest_by_id[record["bead_id"]]
        if record["source_sha"] != source["result_sha"]:
            raise LandingAdapterError("integration result source map does not match manifest source commits")
        if schema_version == 2 and (
            record["store_ref"] != source["store_ref"] or record["work_commit"] != source["work_commit"]
        ):
            raise LandingAdapterError("integration result source map does not match manifest work identity")


def build_direct_receipt(result_path: Path) -> dict[str, object]:
    if not result_path.is_absolute():
        raise LandingAdapterError("integration result path must be absolute")
    resolved_result = result_path.resolve(strict=True)
    result = validate_build_artifact.validate_artifact_text(resolved_result.read_text(encoding="utf-8"))
    if result.schema_id not in {"gc.build.integration-result.v1", "gc.build.integration-result.v2"}:
        raise LandingAdapterError(f"unsupported integration result schema {result.schema_id}")
    schema_version = 2 if result.schema_id.endswith(".v2") else 1
    result_front = result.front_matter
    integration = result_front["integration"]
    if result_front["status"] != "approved" or integration["outcome"] != "ready":
        raise LandingAdapterError("integration result must be approved and ready")

    manifest_path = Path(integration["manifest_path"]).resolve(strict=True)
    manifest = load_artifact(manifest_path, f"gc.build.integration-manifest.v{schema_version}")
    manifest_front = manifest.front_matter
    manifest_integration = manifest_front["integration"]
    artifact_root = Path(manifest_integration["artifact_root"]).resolve(strict=True)
    require_within(resolved_result, artifact_root, "integration result")
    require_within(manifest_path, artifact_root, "integration manifest")

    if result_front["workflow"] != manifest_front["workflow"]:
        raise LandingAdapterError("integration result workflow does not match manifest")
    if result_front["producer"]["attempt"] != manifest_front["producer"]["attempt"]:
        raise LandingAdapterError("integration result attempt does not match manifest")
    if integration["manifest_hash"] != sha256_file(manifest_path):
        raise LandingAdapterError("integration result manifest hash does not match manifest")
    if integration["base_sha"] != manifest_integration["base_sha"]:
        raise LandingAdapterError("integration result base SHA does not match manifest")
    require_source_map_matches_manifest(
        integration["source_map"], manifest_integration["sources"], schema_version
    )

    repository = Path(manifest_integration["repository"]).resolve(strict=True)
    repository_top = Path(run_git(repository, "rev-parse", "--show-toplevel")).resolve(strict=True)
    if repository_top != repository:
        raise LandingAdapterError("integration repository must be the Git top level")
    scratch = Path(integration["scratch_worktree"]).resolve(strict=True)
    scratch_top = Path(run_git(scratch, "rev-parse", "--show-toplevel")).resolve(strict=True)
    if scratch_top != scratch:
        raise LandingAdapterError("integration scratch worktree must be the Git top level")
    candidate_sha = integration["candidate_sha"]
    if run_git(scratch, "rev-parse", "HEAD") != candidate_sha:
        raise LandingAdapterError("integration scratch HEAD does not match candidate SHA")

    remote = manifest_integration["remote"]
    receipt = {
        "workflow_id": str(result_front["workflow"]["id"]),
        "integration_attempt_id": f"attempt-{result_front['producer']['attempt']}",
        "repository_path": str(repository),
        "repository": normalize_remote_identity(repository, remote),
        "remote": remote,
        "target_ref": manifest_integration["target_ref"],
        "expected_target_sha": integration["base_sha"],
        "approved_candidate_sha": candidate_sha,
        "expected_landed_sha": candidate_sha,
        "publication_mode": "direct",
        "integration_result_path": str(resolved_result),
        "integration_result_hash": sha256_file(resolved_result),
    }
    if schema_version == 2:
        receipt["schema_version"] = "2"
        receipt["work_records"] = [
            {
                "store_ref": record["store_ref"],
                "bead_id": record["bead_id"],
                "work_commit": record["work_commit"],
            }
            for record in integration["source_map"]
        ]
    else:
        receipt["work_bead_ids"] = [record["bead_id"] for record in integration["source_map"]]
    return receipt


def receipt_bytes(receipt: dict[str, object]) -> bytes:
    return (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_receipt(path: Path, data: bytes) -> None:
    if not path.is_absolute():
        raise LandingAdapterError("receipt path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise LandingAdapterError("existing landing receipt differs from verified integration result")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def decode_core_result(raw: str, candidate_sha: str) -> dict[str, Any]:
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LandingAdapterError("gc landing record returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise LandingAdapterError("gc landing record result must be an object")
    if result.get("schema_version") != "1" or result.get("ok") is not True:
        raise LandingAdapterError("gc landing record did not report success")
    if re.fullmatch(r"gcl-[0-9a-f]{64}", str(result.get("event_id", ""))) is None:
        raise LandingAdapterError("gc landing record returned an invalid event ID")
    if result.get("observed_landed_sha") != candidate_sha:
        raise LandingAdapterError("gc landing record observed a different landed SHA")
    if not isinstance(result.get("already_recorded"), bool):
        raise LandingAdapterError("gc landing record returned an invalid replay state")
    return result


def record_direct(result_path: Path, receipt_path: Path, gc_bin: str) -> dict[str, Any]:
    receipt = build_direct_receipt(result_path)
    write_receipt(receipt_path, receipt_bytes(receipt))
    completed = subprocess.run(
        [gc_bin, "landing", "record", "--receipt", str(receipt_path), "--json"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise LandingAdapterError("gc landing record failed")
    result = decode_core_result(completed.stdout, str(receipt["approved_candidate_sha"]))
    result["work_record_stampability"] = "stampable" if receipt.get("schema_version") == "2" else "not_stampable"
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record verified landing evidence from an integration result")
    subparsers = parser.add_subparsers(dest="command", required=True)
    direct = subparsers.add_parser("record-direct")
    direct.add_argument("--integration-result", required=True, type=Path)
    direct.add_argument("--receipt", required=True, type=Path)
    direct.add_argument("--gc-bin", default="gc")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        result = record_direct(args.integration_result, args.receipt, args.gc_bin)
    except (
        LandingAdapterError,
        OSError,
        UnicodeDecodeError,
        validate_build_artifact.ValidationError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
