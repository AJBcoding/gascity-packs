from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

import yaml


GASCITY_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = GASCITY_ROOT / "assets" / "scripts" / "integrate_candidate.py"
sys.path.insert(0, str(GASCITY_ROOT / "assets" / "scripts"))

import validate_build_artifact


def git(cwd: pathlib.Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def load_integrator_module():
    spec = importlib.util.spec_from_file_location("gc_integrate_candidate", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load integrate_candidate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def invoke_expected_failure(module, argv: list[str]) -> tuple[int, str]:
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        code = module.main(argv)
    return code, stderr.getvalue()


class IntegrationRepositoryFixture:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.origin = root / "origin.git"
        self.repository = root / "repository"
        self.artifact_root = root / "artifacts"
        self.source_a = root / "source-a"
        self.source_b = root / "source-b"

        subprocess.run(
            ["git", "init", "--bare", "--initial-branch=main", str(self.origin)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "clone", str(self.origin), str(self.repository)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        git(self.repository, "config", "user.name", "Integration Test")
        git(self.repository, "config", "user.email", "integration@example.invalid")
        (self.repository / "base.txt").write_text("base\n", encoding="utf-8")
        git(self.repository, "add", "base.txt")
        git(self.repository, "commit", "-m", "base")
        git(self.repository, "push", "-u", "origin", "main")
        self.base_sha = git(self.repository, "rev-parse", "HEAD").stdout.strip()

        git(self.repository, "worktree", "add", "-b", "source-a", str(self.source_a), self.base_sha)
        (self.source_a / "a.txt").write_text("a\n", encoding="utf-8")
        git(self.source_a, "add", "a.txt")
        git(self.source_a, "commit", "-m", "add a")
        self.source_a_sha = git(self.source_a, "rev-parse", "HEAD").stdout.strip()

        git(self.repository, "worktree", "add", "-b", "source-b", str(self.source_b), self.base_sha)
        (self.source_b / "b.txt").write_text("b\n", encoding="utf-8")
        git(self.source_b, "add", "b.txt")
        git(self.source_b, "commit", "-m", "add b")
        self.source_b_sha = git(self.source_b, "rev-parse", "HEAD").stdout.strip()
        self.artifact_root.mkdir()

    def origin_main(self) -> str:
        return git(self.origin, "rev-parse", "refs/heads/main").stdout.strip()

    def write_manifest(
        self,
        sources: list[dict] | None = None,
        verification: list[list[str]] | None = None,
        *,
        schema_version: int = 1,
    ) -> pathlib.Path:
        summaries = self.artifact_root / "summaries"
        summaries.mkdir(exist_ok=True)
        if sources is None:
            source_rows = [
                self.source_record(
                    "task-b",
                    self.source_b,
                    self.source_b_sha,
                    ["task-a"],
                    ["b.txt"],
                    store_ref="rig:beta" if schema_version == 2 else None,
                    work_commit=self.source_b_sha if schema_version == 2 else None,
                ),
                self.source_record(
                    "task-a",
                    self.source_a,
                    self.source_a_sha,
                    [],
                    ["a.txt"],
                    store_ref="rig:alpha" if schema_version == 2 else None,
                    work_commit=self.source_a_sha if schema_version == 2 else None,
                ),
            ]
        else:
            source_rows = sources
        front_matter = {
            "schema": f"gc.build.integration-manifest.v{schema_version}",
            "workflow": {"id": "build-test-001", "formula": "build-basic"},
            "methodology": {"pack": "gascity", "name": "build-basic"},
            "producer": {"formula": "integrate", "stage": "prepare-manifest", "attempt": 1},
            "status": "approved",
            "integration": {
                "repository": str(self.repository.resolve()),
                "artifact_root": str(self.artifact_root.resolve()),
                "remote": "origin",
                "target_ref": "refs/heads/main",
                "base_sha": self.base_sha,
                "sources": source_rows,
                "verification": verification
                or [
                    [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; assert Path('a.txt').read_text() == 'a\\n'; assert Path('b.txt').read_text() == 'b\\n'",
                    ]
                ],
            },
            "trace": {"upstream": [], "coverage": []},
        }
        body = "\n\n".join(
            f"## {section}\n\n{section} evidence."
            for section in ("Candidate", "Sources", "Verification", "Safety")
        )
        path = self.artifact_root / "integration-manifest.md"
        path.write_text(
            f"---\n{yaml.safe_dump(front_matter, sort_keys=False).rstrip()}\n---\n\n{body}\n",
            encoding="utf-8",
        )
        return path

    def source_record(
        self,
        bead_id: str,
        worktree: pathlib.Path,
        result_sha: str,
        dependencies: list[str],
        changed_paths: list[str],
        *,
        store_ref: str | None = None,
        work_commit: str | None = None,
    ) -> dict:
        summary_path = self.artifact_root / "summaries" / f"{bead_id}.md"
        summary_text = f"# {bead_id}\n"
        summary_path.parent.mkdir(exist_ok=True)
        summary_path.write_text(summary_text, encoding="utf-8")
        record = {
            "bead_id": bead_id,
            "base_sha": self.base_sha,
            "result_sha": result_sha,
            "dependencies": dependencies,
            "worktree": str(worktree.resolve()),
            "changed_paths": changed_paths,
            "summary": {
                "path": str(summary_path.resolve()),
                "hash": f"sha256:{hashlib.sha256(summary_text.encode()).hexdigest()}",
            },
        }
        if store_ref is not None:
            record["store_ref"] = store_ref
        if work_commit is not None:
            record["work_commit"] = work_commit
        return record


class IntegrateCandidateTests(unittest.TestCase):
    def test_v2_propagates_store_scoped_source_identity_into_result(self) -> None:
        module = load_integrator_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = IntegrationRepositoryFixture(pathlib.Path(temp_dir))
            manifest = fixture.write_manifest(schema_version=2)
            result = fixture.artifact_root / "integration-result.md"

            self.assertEqual(module.main(["assemble", "--manifest", str(manifest), "--result", str(result)]), 0)
            artifact = validate_build_artifact.validate_artifact_text(
                result.read_text(encoding="utf-8"),
                expected_schema="gc.build.integration-result.v2",
            )
            self.assertEqual(
                [
                    (row["store_ref"], row["bead_id"], row["work_commit"])
                    for row in artifact.front_matter["integration"]["source_map"]
                ],
                [
                    ("rig:alpha", "task-a", fixture.source_a_sha),
                    ("rig:beta", "task-b", fixture.source_b_sha),
                ],
            )

    def test_assembles_dependency_order_and_writes_ready_result_without_mutating_target(self) -> None:
        self.assertTrue(SCRIPT_PATH.is_file(), f"missing {SCRIPT_PATH}")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), f"{SCRIPT_PATH} must be executable")
        module = load_integrator_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = IntegrationRepositoryFixture(pathlib.Path(temp_dir))
            manifest = fixture.write_manifest()
            result = fixture.artifact_root / "integration-result.md"
            target_before = fixture.origin_main()

            code = module.main(["assemble", "--manifest", str(manifest), "--result", str(result)])

            self.assertEqual(code, 0)
            artifact = validate_build_artifact.validate_artifact_text(
                result.read_text(encoding="utf-8"),
                expected_schema="gc.build.integration-result.v1",
            )
            integration = artifact.front_matter["integration"]
            self.assertEqual(integration["outcome"], "ready")
            self.assertEqual(
                [record["bead_id"] for record in integration["source_map"]],
                ["task-a", "task-b"],
            )
            self.assertEqual(integration["verification"][0]["exit_code"], 0)
            self.assertFalse(integration["push_performed"])
            self.assertFalse(integration["pr_opened"])
            self.assertFalse(integration["target_ref_updated"])
            self.assertEqual(fixture.origin_main(), target_before)

            scratch = pathlib.Path(integration["scratch_worktree"])
            self.assertEqual((scratch / "a.txt").read_text(encoding="utf-8"), "a\n")
            self.assertEqual((scratch / "b.txt").read_text(encoding="utf-8"), "b\n")
            self.assertEqual(git(fixture.repository, "cat-file", "-t", integration["candidate_sha"]).stdout.strip(), "commit")
            self.assertEqual(git(fixture.repository, "cat-file", "-t", integration["tree_sha"]).stdout.strip(), "tree")

    def test_conflict_writes_needs_rework_result_and_aborts_cherry_pick(self) -> None:
        module = load_integrator_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = IntegrationRepositoryFixture(pathlib.Path(temp_dir))
            for worktree, value in ((fixture.source_a, "source a\n"), (fixture.source_b, "source b\n")):
                git(worktree, "reset", "--hard", fixture.base_sha)
                (worktree / "shared.txt").write_text(value, encoding="utf-8")
                git(worktree, "add", "shared.txt")
                git(worktree, "commit", "-m", f"write {value.strip()}")
            fixture.source_a_sha = git(fixture.source_a, "rev-parse", "HEAD").stdout.strip()
            fixture.source_b_sha = git(fixture.source_b, "rev-parse", "HEAD").stdout.strip()
            sources = [
                fixture.source_record("task-b", fixture.source_b, fixture.source_b_sha, ["task-a"], ["shared.txt"]),
                fixture.source_record("task-a", fixture.source_a, fixture.source_a_sha, [], ["shared.txt"]),
            ]
            manifest = fixture.write_manifest(sources=sources, verification=[[sys.executable, "-c", "raise SystemExit(0)"]])
            result = fixture.artifact_root / "integration-result.md"
            target_before = fixture.origin_main()

            code = module.main(["assemble", "--manifest", str(manifest), "--result", str(result)])

            self.assertEqual(code, 1)
            self.assertTrue(result.is_file(), "conflict must emit a typed result")
            artifact = validate_build_artifact.validate_artifact_text(
                result.read_text(encoding="utf-8"), expected_schema="gc.build.integration-result.v1"
            )
            integration = artifact.front_matter["integration"]
            self.assertEqual(integration["outcome"], "needs_rework")
            self.assertEqual(integration["conflict_paths"], ["shared.txt"])
            self.assertEqual(integration["last_clean_candidate_sha"], integration["source_map"][0]["integrated_sha"])
            self.assertEqual(fixture.origin_main(), target_before)
            self.assertEqual(git(pathlib.Path(integration["scratch_worktree"]), "diff", "--name-only", "--diff-filter=U").stdout, "")

    def test_failed_verification_writes_failed_result_with_exact_argv(self) -> None:
        module = load_integrator_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = IntegrationRepositoryFixture(pathlib.Path(temp_dir))
            argv = [sys.executable, "-c", "raise SystemExit(7)"]
            manifest = fixture.write_manifest(verification=[argv])
            result = fixture.artifact_root / "integration-result.md"
            target_before = fixture.origin_main()

            code = module.main(["assemble", "--manifest", str(manifest), "--result", str(result)])

            self.assertEqual(code, 1)
            self.assertTrue(result.is_file(), "verification failure must emit a typed result")
            artifact = validate_build_artifact.validate_artifact_text(
                result.read_text(encoding="utf-8"), expected_schema="gc.build.integration-result.v1"
            )
            integration = artifact.front_matter["integration"]
            self.assertEqual(integration["outcome"], "failed")
            self.assertEqual(integration["verification"], [{"argv": argv, "exit_code": 7, "stdout": "", "stderr": ""}])
            self.assertEqual(git(fixture.repository, "cat-file", "-t", integration["candidate_sha"]).stdout.strip(), "commit")
            self.assertEqual(git(fixture.repository, "cat-file", "-t", integration["tree_sha"]).stdout.strip(), "tree")
            self.assertEqual(fixture.origin_main(), target_before)

    def test_provenance_failure_writes_typed_failed_result_before_candidate_creation(self) -> None:
        module = load_integrator_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = IntegrationRepositoryFixture(pathlib.Path(temp_dir))
            bad_source = fixture.source_record(
                "task-a", fixture.source_a, fixture.base_sha, [], ["a.txt"]
            )
            manifest = fixture.write_manifest(sources=[bad_source])
            result = fixture.artifact_root / "integration-result.md"
            target_before = fixture.origin_main()

            code, stderr = invoke_expected_failure(
                module, ["assemble", "--manifest", str(manifest), "--result", str(result)]
            )

            self.assertEqual(code, 1)
            self.assertIn("does not match worktree HEAD", stderr)
            self.assertTrue(result.is_file(), "valid manifest execution failures must emit a typed result")
            artifact = validate_build_artifact.validate_artifact_text(
                result.read_text(encoding="utf-8"), expected_schema="gc.build.integration-result.v1"
            )
            integration = artifact.front_matter["integration"]
            self.assertEqual(integration["outcome"], "failed")
            self.assertEqual(integration["failure"]["class"], "provenance")
            self.assertIn("does not match worktree HEAD", integration["failure"]["message"])
            self.assertEqual(integration["source_map"], [])
            self.assertEqual(integration["verification"], [])
            self.assertFalse((fixture.artifact_root / "integration").exists())
            self.assertEqual(fixture.origin_main(), target_before)

    def test_verification_argv_is_never_interpreted_by_a_shell(self) -> None:
        module = load_integrator_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = IntegrationRepositoryFixture(pathlib.Path(temp_dir))
            sentinel = fixture.root / "shell-created"
            literal = f"; touch {sentinel}"
            argv = [
                sys.executable,
                "-c",
                "import sys; assert sys.argv[1].startswith('; touch ')",
                literal,
            ]
            manifest = fixture.write_manifest(verification=[argv])
            result = fixture.artifact_root / "integration-result.md"

            self.assertEqual(
                module.main(["assemble", "--manifest", str(manifest), "--result", str(result)]),
                0,
            )
            self.assertFalse(sentinel.exists())
            artifact = validate_build_artifact.validate_artifact_text(
                result.read_text(encoding="utf-8"), expected_schema="gc.build.integration-result.v1"
            )
            self.assertEqual(artifact.front_matter["integration"]["verification"][0]["argv"], argv)

    def test_shared_worktree_accepts_historical_item_commits_in_dependency_order(self) -> None:
        module = load_integrator_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = IntegrationRepositoryFixture(pathlib.Path(temp_dir))
            git(fixture.source_a, "reset", "--hard", fixture.base_sha)
            (fixture.source_a / "first.txt").write_text("first\n", encoding="utf-8")
            git(fixture.source_a, "add", "first.txt")
            git(fixture.source_a, "commit", "-m", "shared item one")
            first_sha = git(fixture.source_a, "rev-parse", "HEAD").stdout.strip()
            (fixture.source_a / "second.txt").write_text("second\n", encoding="utf-8")
            git(fixture.source_a, "add", "second.txt")
            git(fixture.source_a, "commit", "-m", "shared item two")
            second_sha = git(fixture.source_a, "rev-parse", "HEAD").stdout.strip()

            first = fixture.source_record(
                "task-a", fixture.source_a, first_sha, [], ["first.txt"]
            )
            second = fixture.source_record(
                "task-b", fixture.source_a, second_sha, ["task-a"], ["second.txt"]
            )
            second["base_sha"] = first_sha
            verification = [[
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('first.txt').read_text() == 'first\\n'; assert Path('second.txt').read_text() == 'second\\n'",
            ]]
            manifest = fixture.write_manifest(sources=[second, first], verification=verification)
            result = fixture.artifact_root / "integration-result.md"

            self.assertEqual(
                module.main(["assemble", "--manifest", str(manifest), "--result", str(result)]),
                0,
            )
            artifact = validate_build_artifact.validate_artifact_text(
                result.read_text(encoding="utf-8"), expected_schema="gc.build.integration-result.v1"
            )
            integration = artifact.front_matter["integration"]
            self.assertEqual([row["bead_id"] for row in integration["source_map"]], ["task-a", "task-b"])
            scratch = pathlib.Path(integration["scratch_worktree"])
            self.assertEqual((scratch / "first.txt").read_text(encoding="utf-8"), "first\n")
            self.assertEqual((scratch / "second.txt").read_text(encoding="utf-8"), "second\n")

    def test_existing_result_is_never_overwritten(self) -> None:
        module = load_integrator_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = IntegrationRepositoryFixture(pathlib.Path(temp_dir))
            manifest = fixture.write_manifest()
            result = fixture.artifact_root / "integration-result.md"
            result.write_text("keep me\n", encoding="utf-8")

            code, stderr = invoke_expected_failure(
                module, ["assemble", "--manifest", str(manifest), "--result", str(result)]
            )
            self.assertEqual(code, 1)
            self.assertIn("result already exists", stderr)
            self.assertEqual(result.read_text(encoding="utf-8"), "keep me\n")

    def test_existing_attempt_and_symlink_escape_are_rejected_without_mutation(self) -> None:
        module = load_integrator_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = IntegrationRepositoryFixture(pathlib.Path(temp_dir))
            manifest = fixture.write_manifest()
            attempt = fixture.artifact_root / "integration" / "build-test-001" / "attempt-1"
            attempt.mkdir(parents=True)
            marker = attempt / "keep"
            marker.write_text("keep\n", encoding="utf-8")
            result = fixture.artifact_root / "attempt-exists-result.md"

            code, stderr = invoke_expected_failure(
                module, ["assemble", "--manifest", str(manifest), "--result", str(result)]
            )
            self.assertEqual(code, 1)
            self.assertIn("integration attempt already exists", stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = IntegrationRepositoryFixture(pathlib.Path(temp_dir))
            manifest = fixture.write_manifest()
            outside = fixture.root / "outside"
            outside.mkdir()
            (fixture.artifact_root / "escape").symlink_to(outside, target_is_directory=True)
            escaped_result = fixture.artifact_root / "escape" / "result.md"

            code, stderr = invoke_expected_failure(
                module,
                ["assemble", "--manifest", str(manifest), "--result", str(escaped_result)],
            )
            self.assertEqual(code, 1)
            self.assertIn("must resolve within", stderr)
            self.assertFalse((outside / "result.md").exists())


if __name__ == "__main__":
    unittest.main()
