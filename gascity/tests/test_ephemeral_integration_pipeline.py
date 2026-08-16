from __future__ import annotations

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


class EphemeralIntegrationPipelineTests(unittest.TestCase):
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
