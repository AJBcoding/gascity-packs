from __future__ import annotations

import json
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import yaml


TESTS_ROOT = pathlib.Path(__file__).resolve().parent
GASCITY_ROOT = TESTS_ROOT.parent
SCRIPT_PATH = GASCITY_ROOT / "assets" / "scripts" / "record_landing.py"
sys.path.insert(0, str(TESTS_ROOT))

from test_integrate_candidate import IntegrationRepositoryFixture, git, load_integrator_module


def load_record_landing_module():
    scripts_root = SCRIPT_PATH.parent
    sys.path.insert(0, str(scripts_root))
    spec = importlib.util.spec_from_file_location("record_landing", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def integration_fields(result_path: pathlib.Path) -> dict:
    document = result_path.read_text(encoding="utf-8")
    front = document.split("---\n", 2)[1]
    return yaml.safe_load(front)["integration"]


def rewrite_front_matter(path: pathlib.Path, mutate) -> None:
    document = path.read_text(encoding="utf-8")
    _, front, body = document.split("---\n", 2)
    data = yaml.safe_load(front)
    mutate(data)
    path.write_text(f"---\n{yaml.safe_dump(data, sort_keys=False).rstrip()}\n---\n{body}", encoding="utf-8")


def run_adapter(
    result: pathlib.Path,
    receipt: pathlib.Path,
    gc_bin: pathlib.Path,
    *,
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "record-direct",
            "--integration-result",
            str(result),
            "--receipt",
            str(receipt),
            "--gc-bin",
            str(gc_bin),
        ],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def write_core_stub(root: pathlib.Path, payload: object, *, exit_code: int = 0) -> pathlib.Path:
    executable = root / f"core-stub-{len(list(root.glob('core-stub-*')))}"
    raw = payload if isinstance(payload, str) else json.dumps(payload) + "\n"
    executable.write_text(
        f"""#!/usr/bin/env python3
import json
import sys

if sys.argv[1:3] != ["landing", "record"] or sys.argv[3] != "--receipt" or sys.argv[5:] != ["--json"]:
    raise SystemExit(2)
sys.stdout.write({raw!r})
raise SystemExit({exit_code})
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def write_fake_gc(root: pathlib.Path) -> pathlib.Path:
    executable = root / "fake-gc"
    state_path = root / "fake-gc-state.json"
    executable.write_text(
        f"""#!/usr/bin/env python3
import hashlib
import json
import pathlib
import subprocess
import sys

if sys.argv[1:3] != ["landing", "record"] or sys.argv[3] != "--receipt" or sys.argv[5:] != ["--json"]:
    print("unexpected arguments", file=sys.stderr)
    raise SystemExit(2)
receipt = json.loads(pathlib.Path(sys.argv[4]).read_text(encoding="utf-8"))
observed = subprocess.run(
    ["git", "-C", receipt["repository_path"], "ls-remote", "--exit-code", receipt["remote"], receipt["target_ref"]],
    check=True,
    text=True,
    stdout=subprocess.PIPE,
).stdout.split()[0]
if observed != receipt["expected_landed_sha"]:
    print("observed SHA mismatch", file=sys.stderr)
    raise SystemExit(1)
state_path = pathlib.Path({str(state_path)!r})
already_recorded = state_path.exists()
state_path.write_text(json.dumps({{"observations": 2 if already_recorded else 1}}), encoding="utf-8")
digest = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
print(json.dumps({{
    "schema_version": "1",
    "ok": True,
    "event_id": "gcl-" + digest,
    "observed_landed_sha": observed,
    "already_recorded": already_recorded,
}}, sort_keys=True))
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def assembled_ready_fixture(root: pathlib.Path) -> tuple[IntegrationRepositoryFixture, pathlib.Path, str]:
    fixture = IntegrationRepositoryFixture(root)
    manifest = fixture.write_manifest()
    result = fixture.artifact_root / "integration-result.md"
    integrator = load_integrator_module()
    if integrator.main(["assemble", "--manifest", str(manifest), "--result", str(result)]) != 0:
        raise AssertionError("fixture integration failed")
    return fixture, result, integration_fields(result)["candidate_sha"]


class RecordLandingTests(unittest.TestCase):
    def test_remote_identity_matches_core_normalization(self) -> None:
        module = load_record_landing_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            fixture, result, _ = assembled_ready_fixture(root)

            cases = [
                ("build.example:team/repository.git", "build.example:team/repository.git"),
                (f"file://localhost{fixture.origin}", str(fixture.origin)),
            ]
            for configured, expected in cases:
                with self.subTest(configured=configured):
                    git(fixture.repository, "remote", "set-url", "origin", configured)
                    receipt = module.build_direct_receipt(result)
                    self.assertEqual(receipt["repository"], expected)

            link = fixture.repository / "origin-link.git"
            link.symlink_to(fixture.origin, target_is_directory=True)
            git(fixture.repository, "remote", "set-url", "origin", link.name)
            receipt = module.build_direct_receipt(result)
            expected_link_identity = os.path.normpath(os.path.abspath(fixture.repository.resolve() / link.name))
            self.assertEqual(receipt["repository"], expected_link_identity)

    def test_remote_identity_rejects_scp_credentials(self) -> None:
        module = load_record_landing_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            fixture, result, _ = assembled_ready_fixture(root)
            git(fixture.repository, "remote", "set-url", "origin", "builder@build.example:team/repository.git")

            with self.assertRaisesRegex(module.LandingAdapterError, "credentials"):
                module.build_direct_receipt(result)

    def test_record_direct_builds_exact_receipt_and_replays_without_rewriting(self) -> None:
        self.assertTrue(SCRIPT_PATH.is_file(), f"missing {SCRIPT_PATH}")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            fixture, result, candidate = assembled_ready_fixture(root)
            git(
                fixture.repository,
                "push",
                "origin",
                f"{candidate}:refs/heads/main",
                f"--force-with-lease=refs/heads/main:{fixture.base_sha}",
            )

            receipt_path = fixture.artifact_root / "landing-receipt.json"
            fake_gc = write_fake_gc(root)
            command = [
                sys.executable,
                str(SCRIPT_PATH),
                "record-direct",
                "--integration-result",
                str(result),
                "--receipt",
                str(receipt_path),
                "--gc-bin",
                str(fake_gc),
            ]
            first = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_receipt_bytes = receipt_path.read_bytes()
            receipt = json.loads(first_receipt_bytes)
            self.assertEqual(receipt["workflow_id"], "build-test-001")
            self.assertEqual(receipt["integration_attempt_id"], "attempt-1")
            self.assertEqual(receipt["repository_path"], str(fixture.repository.resolve()))
            self.assertEqual(receipt["repository"], str(fixture.origin))
            self.assertEqual(receipt["remote"], "origin")
            self.assertEqual(receipt["target_ref"], "refs/heads/main")
            self.assertEqual(receipt["expected_target_sha"], fixture.base_sha)
            self.assertEqual(receipt["approved_candidate_sha"], candidate)
            self.assertEqual(receipt["expected_landed_sha"], candidate)
            self.assertEqual(receipt["publication_mode"], "direct")
            self.assertEqual(receipt["integration_result_path"], str(result.resolve()))
            self.assertRegex(receipt["integration_result_hash"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(receipt["work_bead_ids"], ["task-a", "task-b"])
            self.assertEqual(receipt_path.stat().st_mode & 0o777, 0o600)
            first_result = json.loads(first.stdout)
            self.assertRegex(first_result["event_id"], r"^gcl-[0-9a-f]{64}$")
            self.assertEqual(first_result["observed_landed_sha"], candidate)
            self.assertFalse(first_result["already_recorded"])

            second = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(receipt_path.read_bytes(), first_receipt_bytes)
            second_result = json.loads(second.stdout)
            self.assertEqual(second_result["event_id"], first_result["event_id"])
            self.assertEqual(second_result["observed_landed_sha"], candidate)
            self.assertTrue(second_result["already_recorded"])

    def test_record_direct_rejects_result_manifest_attempt_drift_before_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            fixture, result, _ = assembled_ready_fixture(root)
            document = result.read_text(encoding="utf-8")
            self.assertIn("attempt: 1", document)
            result.write_text(document.replace("attempt: 1", "attempt: 2", 1), encoding="utf-8")
            receipt_path = fixture.artifact_root / "landing-receipt.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "record-direct",
                    "--integration-result",
                    str(result),
                    "--receipt",
                    str(receipt_path),
                    "--gc-bin",
                    str(write_fake_gc(root)),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("attempt", completed.stderr)
            self.assertFalse(receipt_path.exists())

    def test_record_direct_rejects_relative_integration_result_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            fixture, result, _ = assembled_ready_fixture(root)
            receipt_path = fixture.artifact_root / "landing-receipt.json"
            relative_result = result.relative_to(root)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "record-direct",
                    "--integration-result",
                    str(relative_result),
                    "--receipt",
                    str(receipt_path),
                    "--gc-bin",
                    str(write_fake_gc(root)),
                ],
                cwd=root,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("integration result path must be absolute", completed.stderr)
            self.assertFalse(receipt_path.exists())

    def test_record_direct_rejects_non_ready_result_and_artifact_identity_drift(self) -> None:
        module = load_record_landing_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            fixture, result, _ = assembled_ready_fixture(root)
            rewrite_front_matter(
                result,
                lambda data: (
                    data.update(status="blocked"),
                    data["integration"].update(outcome="failed"),
                    data["integration"]["verification"][0].update(exit_code=1),
                ),
            )
            with self.assertRaisesRegex(module.LandingAdapterError, "approved and ready"):
                module.build_direct_receipt(result)

        for drift in ("manifest hash", "workflow"):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                fixture, result, _ = assembled_ready_fixture(root)
                manifest = pathlib.Path(integration_fields(result)["manifest_path"])
                if drift == "manifest hash":
                    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                    expected = "manifest hash"
                else:
                    rewrite_front_matter(manifest, lambda data: data["workflow"].update(id="different-workflow"))
                    rewrite_front_matter(
                        result,
                        lambda data: data["integration"].update(manifest_hash=module.sha256_file(manifest)),
                    )
                    expected = "workflow"
                with self.assertRaisesRegex(module.LandingAdapterError, expected):
                    module.build_direct_receipt(result)

    def test_record_direct_rejects_paths_outside_contract(self) -> None:
        module = load_record_landing_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            fixture, result, _ = assembled_ready_fixture(root)
            outside_result = root / "outside-result.md"
            outside_result.write_bytes(result.read_bytes())
            with self.assertRaisesRegex(module.LandingAdapterError, "artifact root"):
                module.build_direct_receipt(outside_result)

        for field in ("manifest_path", "repository", "scratch_worktree"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                fixture, result, _ = assembled_ready_fixture(root)
                if field == "manifest_path":
                    manifest = pathlib.Path(integration_fields(result)["manifest_path"])
                    outside_manifest = root / "outside-manifest.md"
                    outside_manifest.write_bytes(manifest.read_bytes())
                    rewrite_front_matter(
                        result,
                        lambda data: data["integration"].update(
                            manifest_path=str(outside_manifest),
                            manifest_hash=module.sha256_file(outside_manifest),
                        ),
                    )
                    expected = "artifact root"
                elif field == "repository":
                    manifest = pathlib.Path(integration_fields(result)["manifest_path"])
                    rewrite_front_matter(manifest, lambda data: data["integration"].update(repository="relative-repo"))
                    rewrite_front_matter(
                        result,
                        lambda data: data["integration"].update(manifest_hash=module.sha256_file(manifest)),
                    )
                    expected = "absolute path"
                else:
                    rewrite_front_matter(
                        result,
                        lambda data: data["integration"].update(scratch_worktree="relative-scratch"),
                    )
                    expected = "absolute path"
                with self.assertRaisesRegex(Exception, expected):
                    module.build_direct_receipt(result)

    def test_record_direct_rejects_scratch_head_drift_and_remote_cardinality(self) -> None:
        module = load_record_landing_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            fixture, result, _ = assembled_ready_fixture(root)
            scratch = pathlib.Path(integration_fields(result)["scratch_worktree"])
            git(scratch, "reset", "--hard", fixture.base_sha)
            with self.assertRaisesRegex(module.LandingAdapterError, "scratch HEAD"):
                module.build_direct_receipt(result)

        for remote_case in ("missing", "ambiguous"):
            with self.subTest(remote_case=remote_case), tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                fixture, result, _ = assembled_ready_fixture(root)
                if remote_case == "missing":
                    git(fixture.repository, "remote", "remove", "origin")
                    expected = "git remote failed"
                else:
                    git(fixture.repository, "remote", "set-url", "--add", "origin", str(root / "second.git"))
                    expected = "exactly one URL"
                with self.assertRaisesRegex(module.LandingAdapterError, expected):
                    module.build_direct_receipt(result)

    def test_record_direct_preserves_a_different_existing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            fixture, result, candidate = assembled_ready_fixture(root)
            receipt = fixture.artifact_root / "landing-receipt.json"
            original = b'{"do_not":"replace"}\n'
            receipt.write_bytes(original)
            core = write_core_stub(
                root,
                json.dumps(
                    {
                        "schema_version": "1",
                        "ok": True,
                        "event_id": "gcl-" + "a" * 64,
                        "observed_landed_sha": candidate,
                        "already_recorded": False,
                    }
                )
                + "\n",
            )

            completed = run_adapter(result, receipt, core)

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("existing landing receipt differs", completed.stderr)
            self.assertEqual(receipt.read_bytes(), original)

    def test_record_direct_rejects_invalid_core_results(self) -> None:
        cases = {
            "nonzero": ("", 1, "gc landing record failed"),
            "trailing JSON": ('{"ok":true}\n{"ok":true}\n', 0, "invalid JSON"),
            "invalid event": (None, 0, "invalid event ID"),
            "wrong SHA": (None, 0, "different landed SHA"),
        }
        for name, (raw, exit_code, expected) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                fixture, result, candidate = assembled_ready_fixture(root)
                payload = {
                    "schema_version": "1",
                    "ok": True,
                    "event_id": "gcl-" + ("z" if name == "invalid event" else "a") * 64,
                    "observed_landed_sha": fixture.base_sha if name == "wrong SHA" else candidate,
                    "already_recorded": False,
                }
                core = write_core_stub(root, raw if raw is not None else json.dumps(payload) + "\n", exit_code=exit_code)
                receipt = fixture.artifact_root / "landing-receipt.json"

                completed = run_adapter(result, receipt, core)

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(expected, completed.stderr)


if __name__ == "__main__":
    unittest.main()
