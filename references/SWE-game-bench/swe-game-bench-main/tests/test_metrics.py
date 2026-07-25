import tempfile
import unittest
from pathlib import Path

from swe_game_bench.dataset import Instance
from swe_game_bench.passk import record_detail, summarize_details
from swe_game_bench.reporting import (
    run_hits_all_targets,
    run_hits_any_target,
    run_patch_applied,
)


def make_instance() -> Instance:
    return Instance(
        instance_id="repo-1",
        repo="repo",
        issue_number=1,
        issue_url="",
        base_sha="base",
        fix_sha="fix",
        target_files=["Assets/A.cs", "Assets/B.cs"],
        test_class="Tests",
        test_platform="EditMode",
        unity_bucket="test",
    )


class MetricTests(unittest.TestCase):
    def test_record_detail_distinguishes_any_and_all_target_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            patch = Path(tmp) / "candidate.patch"
            patch.write_text(
                "diff --git a/Assets/A.cs b/Assets/A.cs\n"
                "--- a/Assets/A.cs\n"
                "+++ b/Assets/A.cs\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n",
                encoding="utf-8",
            )
            details = {}

            record_detail(
                details,
                make_instance(),
                1,
                passed=False,
                xml_path=Path(tmp) / "missing.xml",
                patch_path=patch,
                patch_applied=True,
            )

            run = details["instances"]["repo-1"]["runs"][0]
            self.assertTrue(run["hit_target_any"])
            self.assertFalse(run["hit_target_all"])
            self.assertFalse(run["hit_target"])

    def test_all_target_hit_allows_extra_modified_files(self) -> None:
        run = {"files_modified": ["Assets/A.cs", "Assets/B.cs", "Assets/C.cs"]}
        targets = ["Assets/A.cs", "Assets/B.cs"]

        self.assertTrue(run_hits_any_target(run, targets))
        self.assertTrue(run_hits_all_targets(run, targets))

    def test_clean_application_status_is_required_when_explicit(self) -> None:
        self.assertTrue(run_patch_applied({"patch_applied": True}))
        self.assertFalse(
            run_patch_applied(
                {
                    "patch_applied": False,
                    "passed": True,
                    "test_case_summary": {"total": 1},
                }
            )
        )

    def test_legacy_test_results_prove_application_succeeded(self) -> None:
        self.assertTrue(
            run_patch_applied(
                {"passed": False, "test_case_summary": {"total": 1}}
            )
        )
        self.assertFalse(
            run_patch_applied(
                {"passed": False, "test_case_summary": {"total": 0}}
            )
        )

    def test_summarizer_migrates_legacy_loose_hit_to_all_target_hit(self) -> None:
        details = {
            "instances": {
                "repo-1": {
                    "target_files": ["Assets/A.cs", "Assets/B.cs"],
                    "runs": [
                        {
                            "run_idx": 1,
                            "hit_target": True,
                            "files_modified": ["Assets/A.cs"],
                            "passed": False,
                        }
                    ],
                }
            }
        }

        summarize_details(details)

        run = details["instances"]["repo-1"]["runs"][0]
        self.assertTrue(run["hit_target_any"])
        self.assertFalse(run["hit_target_all"])
        self.assertFalse(run["hit_target"])


if __name__ == "__main__":
    unittest.main()
