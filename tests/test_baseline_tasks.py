from __future__ import annotations

import tempfile
from pathlib import Path

from game_agent.baseline_tasks import TASKS, get_task


def test_registry_has_two_tasks_per_difficulty() -> None:
    assert len(TASKS) == 6
    assert {level: sum(task.difficulty == level for task in TASKS.values()) for level in ("simple", "medium", "hard")} == {
        "simple": 2, "medium": 2, "hard": 2,
    }
    assert all(task.task_en and task.root_cause_file for task in TASKS.values())


def test_options_listener_injector_and_oracle_are_exact() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "Assets/Scripts/UI/OptionUI.cs"
        target.parent.mkdir(parents=True)
        target.write_text(
            "class OptionUI { void Awake() {\n"
            "        soundEffectsButton.onClick.AddListener(() =>\n"
            "        {\n"
            "            SoundManager.Instance.ChangeVolume();\n"
            "            UpdateVisual();\n"
            "        });\n\n"
            "} }", encoding="utf-8",
        )
        task = get_task("options-sfx-button-listener")
        assert task.oracle(root, Path("Unity"))
        task.inject(root, root / "artifacts", Path("Unity"))
        assert not task.oracle(root, Path("Unity"))
        assert (root / "artifacts/defect-manifest.json").is_file()


def test_state_event_injector_is_scoped_to_interaction_method() -> None:
    statement = "OnStateChanged?.Invoke(this, EventArgs.Empty);"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "Assets/Scripts/KitchenGameManager.cs"
        target.parent.mkdir(parents=True)
        target.write_text(
            "class KitchenGameManager {\n"
            "    private void Update() {\n        " + statement + "\n    }\n"
            "    private void GameInput_OnInteraction(object sender, System.EventArgs e) {\n"
            "        state = State.CountdownToStart;\n        " + statement + "\n    }\n"
            "    private void Pause() {\n        " + statement + "\n    }\n"
            "}\n",
            encoding="utf-8",
        )
        task = get_task("state-event-publication")
        manifest = task.inject(root, root / "artifacts", Path("Unity"))
        defective = target.read_text(encoding="utf-8")
        assert defective.count(statement) == 2
        assert manifest["replacement_count"] == 1
        assert not task.oracle(root, Path("Unity"))
