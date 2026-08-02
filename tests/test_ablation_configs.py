from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from game_agent.aci import AciConfig
from game_agent.baseline_runner import BaselineCase, StateEventBaselineRunner


ROOT = Path(__file__).parents[1]
CONFIG_ROOT = ROOT / "configs" / "ablation"


class AblationConfigMatrixTest(unittest.TestCase):
    def setUp(self) -> None:
        self.configs = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(CONFIG_ROOT.glob("group*.json"))
        }
        self.base = self.configs["group1-full.json"]

    def test_every_group_uses_the_verified_fixed_conditions(self):
        self.assertEqual(9, len(self.configs))
        for config in self.configs.values():
            self.assertEqual(81920, config["experiment"]["max_total_tokens"])
            self.assertEqual("en", config["experiment"]["task_language"])
            self.assertEqual(
                "artifacts/project-graph/kitchen-chaos-causal-full/project-graph.json",
                config["context"]["graph_path"],
            )
            graph = ROOT / config["context"]["graph_path"]
            self.assertEqual(
                hashlib.sha256(graph.read_bytes()).hexdigest(),
                config["context"]["graph_sha256"],
            )
            self.assertEqual(["editmode", "playmode"], config["aci"]["required_validation_modes"])
            self.assertEqual(
                ["compile", "editmode", "playmode"],
                config["validation"]["modes"],
            )
            AciConfig(**config["aci"])

    def test_each_treatment_changes_exactly_one_runtime_factor(self):
        treatments = {
            "group2-no-p1.json": ("aci", "evidence_recovery_enabled"),
            "group3-no-evidence.json": ("aci", "evidence_artifact_enabled"),
            "group4-no-dynamic-tools.json": ("aci", "dynamic_tool_exposure_enabled"),
            "group5-no-search-budget.json": ("aci", "bounded_search_enabled"),
            "group6-no-graph.json": ("context", "enabled"),
            "group7-no-contract.json": ("aci", "submission_contract_enabled"),
            "group8-no-typed-mutations.json": ("aci", "typed_mutations_enabled"),
            "group9-no-validation.json": ("aci", "validation_gates_enabled"),
        }
        for filename, (section, key) in treatments.items():
            config = self.configs[filename]
            self.assertTrue(self.base[section][key])
            self.assertFalse(config[section][key])
            for runtime_section in ("experiment", "model", "environment", "agent", "skills", "context", "aci", "workspace", "validation"):
                base_values = dict(self.base[runtime_section])
                treatment_values = dict(config[runtime_section])
                if runtime_section == section:
                    base_values.pop(key)
                    treatment_values.pop(key)
                self.assertEqual(
                    base_values,
                    treatment_values,
                    f"{filename} changes more than {section}.{key}",
                )

    def test_baseline_runner_preserves_disabled_treatments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            for filename, expected_context, expected_typed in (
                ("group6-no-graph.json", False, True),
                ("group8-no-typed-mutations.json", True, False),
            ):
                artifacts = root / filename
                artifacts.mkdir()
                runner = StateEventBaselineRunner(BaselineCase(
                    source_project=project,
                    config_path=CONFIG_ROOT / filename,
                    artifact_dir=artifacts,
                    editor_path=root / "Unity.exe",
                    variant="innovation",
                ))
                prepared, _ = runner._prepare_config(project, filename)
                self.assertIs(expected_context, prepared["context"]["enabled"])
                self.assertIs(expected_typed, prepared["aci"]["typed_mutations_enabled"])


if __name__ == "__main__":
    unittest.main()
