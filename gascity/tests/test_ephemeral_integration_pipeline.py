from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


TESTS_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_ROOT))

import test_formula_assets
from test_integrate_candidate import IntegrationRepositoryFixture, git, validate_build_artifact
from test_record_landing import load_record_landing_module, rewrite_front_matter, write_core_stub


def write_observing_gc(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    executable = root / "observing-gc"
    state_path = root / "observing-state.json"
    invocation_path = root / "observing-invocations.jsonl"
    executable.write_text(
        f"""#!/usr/bin/env python3
import hashlib
import json
import pathlib
import subprocess
import sys

invocation_path = pathlib.Path({str(invocation_path)!r})
with invocation_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] != ["landing", "record"] or sys.argv[3] != "--receipt" or sys.argv[5:] != ["--json"]:
    raise SystemExit(2)
receipt_path = pathlib.Path(sys.argv[4])
receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
observed = subprocess.run(
    ["git", "-C", receipt["repository_path"], "ls-remote", "--exit-code", receipt["remote"], receipt["target_ref"]],
    check=True,
    text=True,
    stdout=subprocess.PIPE,
).stdout.split()[0]
if observed != receipt["expected_landed_sha"]:
    raise SystemExit(1)
state_path = pathlib.Path({str(state_path)!r})
observations = json.loads(state_path.read_text())["observations"] if state_path.exists() else 0
state_path.write_text(json.dumps({{"observations": observations + 1}}), encoding="utf-8")
digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
print(json.dumps({{
    "schema_version": "1",
    "ok": True,
    "event_id": "gcl-" + digest,
    "observed_landed_sha": observed,
    "already_recorded": observations > 0,
}}, sort_keys=True))
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable, state_path, invocation_path


class EphemeralIntegrationPipelineTests(unittest.TestCase):
    def test_installed_adapter_mutations_preserve_receipt_and_remote_refs(self) -> None:
        gascity_root = TESTS_ROOT.parent
        for mutation in ("candidate", "manifest_hash", "target_ref", "core_observation"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                fixture = IntegrationRepositoryFixture(root)
                manifest = fixture.write_manifest()
                scripts = fixture.repository / ".gc/scripts"
                scripts.mkdir(parents=True)
                for script_name in (
                    "integrate_candidate.py",
                    "record_landing.py",
                    "validate_build_artifact.py",
                ):
                    shutil.copy2(gascity_root / "assets/scripts" / script_name, scripts / script_name)
                shutil.copytree(gascity_root / "schemas/build", fixture.repository / "schemas/build")
                result = fixture.artifact_root / "integration-result.md"
                assembled = subprocess.run(
                    [
                        sys.executable,
                        str(scripts / "integrate_candidate.py"),
                        "assemble",
                        "--manifest",
                        str(manifest),
                        "--result",
                        str(result),
                    ],
                    cwd=fixture.repository,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.assertEqual(assembled.returncode, 0, assembled.stderr)
                integration = validate_build_artifact.validate_artifact_text(
                    result.read_text(encoding="utf-8"),
                    expected_schema="gc.build.integration-result.v1",
                ).front_matter["integration"]
                candidate = integration["candidate_sha"]
                scratch = pathlib.Path(integration["scratch_worktree"])
                git(
                    scratch,
                    "push",
                    "origin",
                    f"{candidate}:refs/heads/main",
                    f"--force-with-lease=refs/heads/main:{fixture.base_sha}",
                )

                gc_bin, _, _ = write_observing_gc(root)
                receipt = fixture.artifact_root / "landing-receipt.json"
                base_command = [
                    sys.executable,
                    str(scripts / "record_landing.py"),
                    "record-direct",
                    "--integration-result",
                    str(result),
                    "--receipt",
                    str(receipt),
                    "--gc-bin",
                    str(gc_bin),
                ]
                initial = subprocess.run(
                    base_command,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.assertEqual(initial.returncode, 0, initial.stderr)
                original_receipt = receipt.read_bytes()
                original_refs = git(
                    fixture.origin,
                    "for-each-ref",
                    "--format=%(refname) %(objectname)",
                ).stdout

                command = list(base_command)
                if mutation == "candidate":
                    rewrite_front_matter(
                        result,
                        lambda data: data["integration"].update(candidate_sha=fixture.base_sha),
                    )
                elif mutation == "manifest_hash":
                    rewrite_front_matter(
                        result,
                        lambda data: data["integration"].update(manifest_hash="sha256:" + "0" * 64),
                    )
                elif mutation == "target_ref":
                    rewrite_front_matter(
                        manifest,
                        lambda data: data["integration"].update(target_ref="refs/heads/other"),
                    )
                    module = load_record_landing_module()
                    rewrite_front_matter(
                        result,
                        lambda data: data["integration"].update(manifest_hash=module.sha256_file(manifest)),
                    )
                else:
                    wrong_core = write_core_stub(
                        root,
                        {
                            "schema_version": "1",
                            "ok": True,
                            "event_id": "gcl-" + "a" * 64,
                            "observed_landed_sha": fixture.base_sha,
                            "already_recorded": False,
                        },
                    )
                    command[-1] = str(wrong_core)

                rejected = subprocess.run(
                    command,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(receipt.read_bytes(), original_receipt)
                self.assertEqual(
                    git(fixture.origin, "for-each-ref", "--format=%(refname) %(objectname)").stdout,
                    original_refs,
                )

    def test_installed_adapter_records_only_the_lease_published_candidate(self) -> None:
        gascity_root = TESTS_ROOT.parent
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            fixture = IntegrationRepositoryFixture(root)
            target_ref = "refs/heads/verified-candidate"
            git(fixture.repository, "push", "origin", f"{fixture.base_sha}:{target_ref}")
            manifest = fixture.write_manifest()
            rewrite_front_matter(
                manifest,
                lambda data: data["integration"].update(target_ref=target_ref),
            )
            refs_before = git(
                fixture.origin,
                "for-each-ref",
                "--format=%(refname) %(objectname)",
                "refs/heads",
            ).stdout.splitlines()

            scripts = fixture.repository / ".gc/scripts"
            scripts.mkdir(parents=True)
            for script_name in (
                "integrate_candidate.py",
                "record_landing.py",
                "validate_build_artifact.py",
            ):
                shutil.copy2(gascity_root / "assets/scripts" / script_name, scripts / script_name)
            shutil.copytree(gascity_root / "schemas/build", fixture.repository / "schemas/build")
            result = fixture.artifact_root / "integration-result.md"
            assembled = subprocess.run(
                [
                    sys.executable,
                    str(scripts / "integrate_candidate.py"),
                    "assemble",
                    "--manifest",
                    str(manifest),
                    "--result",
                    str(result),
                ],
                cwd=fixture.repository,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(assembled.returncode, 0, assembled.stderr)
            integration = validate_build_artifact.validate_artifact_text(
                result.read_text(encoding="utf-8"),
                expected_schema="gc.build.integration-result.v1",
            ).front_matter["integration"]
            candidate = integration["candidate_sha"]
            scratch = pathlib.Path(integration["scratch_worktree"])

            published = git(
                scratch,
                "push",
                "origin",
                f"{candidate}:{target_ref}",
                f"--force-with-lease={target_ref}:{fixture.base_sha}",
            )
            self.assertEqual(published.returncode, 0, published.stderr)

            gc_bin, state_path, invocation_path = write_observing_gc(root)
            receipt = fixture.artifact_root / "landing-receipt.json"
            command = [
                sys.executable,
                str(scripts / "record_landing.py"),
                "record-direct",
                "--integration-result",
                str(result),
                "--receipt",
                str(receipt),
                "--gc-bin",
                str(gc_bin),
            ]
            first = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(first.returncode, 0, first.stderr)
            receipt_bytes = receipt.read_bytes()
            second = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(second.returncode, 0, second.stderr)

            first_result = json.loads(first.stdout)
            second_result = json.loads(second.stdout)
            self.assertEqual(first_result["event_id"], second_result["event_id"])
            self.assertFalse(first_result["already_recorded"])
            self.assertTrue(second_result["already_recorded"])
            self.assertEqual(receipt.read_bytes(), receipt_bytes)
            self.assertEqual(json.loads(state_path.read_text())["observations"], 2)

            refs_after = git(
                fixture.origin,
                "for-each-ref",
                "--format=%(refname) %(objectname)",
                "refs/heads",
            ).stdout.splitlines()
            self.assertEqual(
                refs_after,
                [
                    f"refs/heads/main {fixture.base_sha}",
                    f"{target_ref} {candidate}",
                ],
            )
            self.assertNotEqual(refs_after, refs_before)
            self.assertFalse((fixture.repository / ".beads").exists())
            invocations = [json.loads(line) for line in invocation_path.read_text().splitlines()]
            self.assertEqual(
                invocations,
                [
                    ["landing", "record", "--receipt", str(receipt), "--json"],
                    ["landing", "record", "--receipt", str(receipt), "--json"],
                ],
            )
            invocation_text = "\n".join(" ".join(argv) for argv in invocations).lower()
            for forbidden in (
                "git push",
                "gh pr",
                "bd close",
                "mysql",
                "refinery",
                "polecat",
                "gastown",
            ):
                self.assertNotIn(forbidden, invocation_text)

    def test_public_build_graph_reviews_the_exact_assembled_candidate(self) -> None:
        gascity_root = TESTS_ROOT.parent
        build = test_formula_assets.resolve_formula(gascity_root, "build-basic")
        step_ids = [step["id"] for step in build["steps"]]
        self.assertLess(step_ids.index("implement"), step_ids.index("integrate"))
        self.assertLess(step_ids.index("implement-same-session"), step_ids.index("integrate"))
        self.assertLess(step_ids.index("integrate"), step_ids.index("summarize-implementation"))
        self.assertLess(step_ids.index("summarize-implementation"), step_ids.index("review"))
        self.assertLess(step_ids.index("review"), step_ids.index("finalize"))
        self.assertLess(step_ids.index("finalize"), step_ids.index("publish"))

        continuation = test_formula_assets.resolve_formula(gascity_root, "build-from-convoy")
        continuation_steps = {step["id"]: step for step in continuation["steps"]}
        self.assertEqual(
            continuation_steps["integrate"]["needs"],
            ["implement", "implement-same-session"],
        )
        self.assertEqual(continuation_steps["prepare-review"]["needs"], ["integrate"])

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = IntegrationRepositoryFixture(pathlib.Path(temp_dir))
            manifest = fixture.write_manifest()
            result = fixture.artifact_root / "integration-result.md"
            target_before = fixture.origin_main()
            installed_helper = fixture.repository / ".gc/scripts/integrate_candidate.py"
            installed_helper.parent.mkdir(parents=True)
            for script_name in ("integrate_candidate.py", "validate_build_artifact.py"):
                shutil.copy2(
                    gascity_root / "assets/scripts" / script_name,
                    installed_helper.parent / script_name,
                )
            installed_schemas = fixture.repository / "schemas/build"
            shutil.copytree(gascity_root / "schemas/build", installed_schemas)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(installed_helper),
                    "assemble",
                    "--manifest",
                    str(manifest),
                    "--result",
                    str(result),
                ],
                cwd=fixture.repository,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            manifest_artifact = validate_build_artifact.validate_artifact_text(
                manifest.read_text(encoding="utf-8"),
                expected_schema="gc.build.integration-manifest.v1",
            )
            result_artifact = validate_build_artifact.validate_artifact_text(
                result.read_text(encoding="utf-8"),
                expected_schema="gc.build.integration-result.v1",
            )
            integration = result_artifact.front_matter["integration"]
            self.assertEqual(integration["outcome"], "ready")
            self.assertEqual(integration["base_sha"], manifest_artifact.front_matter["integration"]["base_sha"])
            self.assertEqual([row["bead_id"] for row in integration["source_map"]], ["task-a", "task-b"])
            self.assertEqual(git(fixture.repository, "rev-parse", f"{integration['candidate_sha']}^{{tree}}").stdout.strip(), integration["tree_sha"])
            self.assertEqual(fixture.origin_main(), target_before)
            self.assertFalse(integration["push_performed"])
            self.assertFalse(integration["pr_opened"])
            self.assertFalse(integration["target_ref_updated"])


if __name__ == "__main__":
    unittest.main()
