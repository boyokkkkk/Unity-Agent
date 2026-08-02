from __future__ import annotations

import difflib
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


TASK_SCHEMA_VERSION = "game-agent-kitchen-chaos-task-v1"


@dataclass(frozen=True, slots=True)
class BaselineTaskSpec:
    id: str
    difficulty: str
    task_en: str
    root_cause_file: str
    relevant_files: tuple[str, ...]
    inject: Callable[[Path, Path, Path], dict[str, Any]]
    oracle: Callable[[Path, Path], bool]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _script_edit(
    project: Path,
    artifact_dir: Path,
    *,
    relative: str,
    old: str,
    new: str,
    task_id: str,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    target = project / relative
    source = target.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{task_id}: expected one exact injection anchor in {relative}, found {count}")
    defective = source.replace(old, new, 1)
    target.write_text(defective, encoding="utf-8")
    return _record_script_edit(
        artifact_dir,
        relative=relative,
        source=source,
        defective=defective,
        task_id=task_id,
    )


def _record_script_edit(
    artifact_dir: Path,
    *,
    relative: str,
    source: str,
    defective: str,
    task_id: str,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    patch = "".join(difflib.unified_diff(
        source.splitlines(keepends=True), defective.splitlines(keepends=True),
        fromfile=relative, tofile=relative,
    ))
    (artifact_dir / "defect.patch").write_text(patch, encoding="utf-8")
    manifest = {
        "schema_version": TASK_SCHEMA_VERSION,
        "task_id": task_id,
        "kind": "script_exact_replacement",
        "target": relative,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "defective_sha256": hashlib.sha256(defective.encode()).hexdigest(),
        "replacement_count": 1,
        "patch": "defect.patch",
    }
    _write_json(artifact_dir / "defect-manifest.json", manifest)
    return manifest


def _t1_inject(project: Path, artifacts: Path, _editor: Path) -> dict[str, Any]:
    path = "Assets/Scripts/KitchenGameManager.cs"
    source = (project / path).read_text(encoding="utf-8")
    method = re.search(
        r"private\s+void\s+GameInput_OnInteraction\s*\([^)]*\)\s*\{(?P<body>.*?)\n\s*\}",
        source, re.DOTALL,
    )
    if method is None:
        raise ValueError("T1: GameInput_OnInteraction was not found")
    statement = "OnStateChanged?.Invoke(this, EventArgs.Empty);"
    body = method.group("body")
    if body.count(statement) != 1 or "state = State.CountdownToStart;" not in body:
        raise ValueError("T1: expected countdown transition followed by one event publication")
    defective_body = body.replace(statement, "", 1)
    defective = source[: method.start("body")] + defective_body + source[method.end("body") :]
    (project / path).write_text(defective, encoding="utf-8")
    return _record_script_edit(
        artifacts,
        relative=path,
        source=source,
        defective=defective,
        task_id="state-event-publication",
    )


def _t1_oracle(project: Path, _editor: Path) -> bool:
    text = (project / "Assets/Scripts/KitchenGameManager.cs").read_text(encoding="utf-8")
    match = re.search(
        r"private\s+void\s+GameInput_OnInteraction\s*\([^)]*\)\s*\{(?P<body>.*?)\n\s*\}",
        text, re.DOTALL,
    )
    if match is None:
        return False
    body = match.group("body")
    return body.find("OnStateChanged?.Invoke(this, EventArgs.Empty);") > body.find(
        "state = State.CountdownToStart;"
    ) >= 0


OPTION_LISTENER = """        soundEffectsButton.onClick.AddListener(() =>
        {
            SoundManager.Instance.ChangeVolume();
            UpdateVisual();
        });

"""


def _t5_inject(project: Path, artifacts: Path, _editor: Path) -> dict[str, Any]:
    return _script_edit(
        project, artifacts, relative="Assets/Scripts/UI/OptionUI.cs",
        old=OPTION_LISTENER, new="", task_id="options-sfx-button-listener",
    )


def _t5_oracle(project: Path, _editor: Path) -> bool:
    text = (project / "Assets/Scripts/UI/OptionUI.cs").read_text(encoding="utf-8")
    return text.count(OPTION_LISTENER.strip()) == 1


DELIVERY_SUBSCRIPTIONS = """        DeliveryManager.Instance.OnRecipeSuccess += DeliveryManager_OnRecipeSuccess;
        DeliveryManager.Instance.OnRecipeFailed += DeliveryManager_OnRecipeFailed;

"""


def _t2_inject(project: Path, artifacts: Path, _editor: Path) -> dict[str, Any]:
    return _script_edit(
        project, artifacts, relative="Assets/Scripts/UI/DeliveryResultUI.cs",
        old=DELIVERY_SUBSCRIPTIONS, new="", task_id="delivery-result-subscription",
    )


def _t2_oracle(project: Path, _editor: Path) -> bool:
    text = (project / "Assets/Scripts/UI/DeliveryResultUI.cs").read_text(encoding="utf-8")
    return all(text.count(line.strip()) == 1 for line in DELIVERY_SUBSCRIPTIONS.splitlines() if "+=" in line)


UNITY_MUTATOR = r'''using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

public static class GameAgentBaselineTaskMutation {
    static string Arg(string name) {
        var args = Environment.GetCommandLineArgs();
        var i = Array.IndexOf(args, name);
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : "";
    }
    public static void Run() {
        var task = Arg("-gameAgentTask");
        var mode = Arg("-gameAgentMode");
        var output = Arg("-gameAgentOutput");
        bool ok = mode == "inject" ? Inject(task) : Check(task);
        File.WriteAllText(output, "{\"ok\":" + (ok ? "true" : "false") + "}");
        if (!ok) throw new Exception("Task mutation/oracle failed: " + task + " " + mode);
    }
    static GameObject Load(string path) {
        var root = PrefabUtility.LoadPrefabContents(path);
        if (root == null) throw new Exception("Cannot load prefab " + path);
        return root;
    }
    static Component Find(GameObject root, string typeName) {
        return root.GetComponentsInChildren<Component>(true).FirstOrDefault(
            c => c != null && c.GetType().Name == typeName);
    }
    static bool Inject(string task) {
        if (task == "plates-scriptableobject-reference") {
            const string path = "Assets/Prefabs/Counters/PlatesCounter.prefab";
            var root = Load(path);
            try {
                var component = Find(root, "PlatesCounter");
                var property = new SerializedObject(component).FindProperty("plateKitchenObjectSO");
                property.objectReferenceValue = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(
                    "Assets/ScriptableObjects/KitchenObjectSO/Bread.asset");
                property.serializedObject.ApplyModifiedPropertiesWithoutUndo();
                PrefabUtility.SaveAsPrefabAsset(root, path);
                return true;
            } finally { PrefabUtility.UnloadPrefabContents(root); }
        }
        if (task == "stove-progress-reference") {
            const string path = "Assets/Prefabs/Counters/StoveCounter.prefab";
            var root = Load(path);
            try {
                var component = Find(root, "ProgressBarUI");
                var property = new SerializedObject(component).FindProperty("hasProgressGameObject");
                var wrong = root.GetComponentsInChildren<Transform>(true)
                    .Select(t => t.gameObject).First(go => go != root && go.GetComponent("StoveCounter") == null);
                property.objectReferenceValue = wrong;
                property.serializedObject.ApplyModifiedPropertiesWithoutUndo();
                PrefabUtility.SaveAsPrefabAsset(root, path);
                return true;
            } finally { PrefabUtility.UnloadPrefabContents(root); }
        }
        if (task == "stove-visual-component") {
            const string path = "Assets/Prefabs/Counters/StoveCounter.prefab";
            var root = Load(path);
            try {
                var component = Find(root, "StoveCounterVisual");
                if (component == null) return false;
                UnityEngine.Object.DestroyImmediate(component, true);
                PrefabUtility.SaveAsPrefabAsset(root, path);
                return true;
            } finally { PrefabUtility.UnloadPrefabContents(root); }
        }
        return false;
    }
    static bool Check(string task) {
        string path = task == "plates-scriptableobject-reference"
            ? "Assets/Prefabs/Counters/PlatesCounter.prefab"
            : "Assets/Prefabs/Counters/StoveCounter.prefab";
        var root = Load(path);
        try {
            if (task == "plates-scriptableobject-reference") {
                var p = new SerializedObject(Find(root, "PlatesCounter")).FindProperty("plateKitchenObjectSO");
                return p.objectReferenceValue != null && p.objectReferenceValue.name == "Plate";
            }
            if (task == "stove-progress-reference") {
                var p = new SerializedObject(Find(root, "ProgressBarUI")).FindProperty("hasProgressGameObject");
                var go = p.objectReferenceValue as GameObject;
                return go != null && go.GetComponents<Component>().Any(c => c != null &&
                    c.GetType().GetInterfaces().Any(i => i.Name == "IHasProgress"));
            }
            if (task == "stove-visual-component") {
                var c = Find(root, "StoveCounterVisual");
                if (c == null) return false;
                var so = new SerializedObject(c);
                var refs = new[] { "stoveCounter", "stoveOnGameObject", "particlesGameObject" };
                return refs.All(name => { var p = so.FindProperty(name); return p != null && p.objectReferenceValue != null; });
            }
            return false;
        } finally { PrefabUtility.UnloadPrefabContents(root); }
    }
}
'''


def _run_unity_task(project: Path, editor: Path, task_id: str, mode: str, output: Path) -> bool:
    helper = project / "Assets/Editor/GameAgentBaselineTaskMutation.cs"
    meta = Path(str(helper) + ".meta")
    helper.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    log_path = output.with_suffix(".unity.log")
    helper.write_text(UNITY_MUTATOR, encoding="utf-8")
    try:
        command = [
            str(editor), "-batchmode", "-quit", "-projectPath", str(project),
            "-logFile", str(log_path.resolve()),
            "-executeMethod", "GameAgentBaselineTaskMutation.Run",
            "-gameAgentTask", task_id, "-gameAgentMode", mode,
            "-gameAgentOutput", str(output.resolve()),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=1200, check=False)
        if completed.returncode != 0 or not output.is_file():
            log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
            diagnostics = [
                line.strip() for line in log_text.splitlines()
                if re.search(r"(?:error\s+CS\d+|Scripts have compiler errors|Unhandled Exception)", line)
            ]
            detail = "\n".join(dict.fromkeys(diagnostics[-20:]))
            raise RuntimeError(
                f"Unity {mode} failed for {task_id} ({completed.returncode}): "
                f"log={log_path.resolve()}\n{detail or completed.stdout[-2000:] + completed.stderr[-2000:]}"
            )
        return bool(json.loads(output.read_text(encoding="utf-8")).get("ok"))
    finally:
        helper.unlink(missing_ok=True)
        meta.unlink(missing_ok=True)


def _asset_inject(task_id: str) -> Callable[[Path, Path, Path], dict[str, Any]]:
    def inject(project: Path, artifacts: Path, editor: Path) -> dict[str, Any]:
        status = artifacts / f"{task_id}-inject.json"
        if not _run_unity_task(project, editor, task_id, "inject", status):
            raise RuntimeError(f"Asset injection did not activate for {task_id}")
        manifest = {
            "schema_version": TASK_SCHEMA_VERSION,
            "task_id": task_id,
            "kind": "unity_editor_asset_mutation",
            "editor_api": True,
            "status": status.name,
        }
        _write_json(artifacts / "defect-manifest.json", manifest)
        return manifest
    return inject


def _asset_oracle(task_id: str) -> Callable[[Path, Path], bool]:
    def oracle(project: Path, editor: Path) -> bool:
        output = project.parent / f".{task_id}-oracle.json"
        try:
            return _run_unity_task(project, editor, task_id, "check", output)
        finally:
            output.unlink(missing_ok=True)
    return oracle


TASKS: dict[str, BaselineTaskSpec] = {
    "state-event-publication": BaselineTaskSpec(
        "state-event-publication", "simple",
        "After the player presses interact on the start screen, the game enters countdown but the tutorial and countdown UI do not refresh. Locate the root cause, make the smallest repair, and validate it.",
        "Assets/Scripts/KitchenGameManager.cs",
        ("Assets/Scripts/KitchenGameManager.cs", "Assets/Scripts/UI/TutorialUI.cs", "Assets/Scripts/UI/GameStartCountdownUI.cs"),
        _t1_inject, _t1_oracle,
    ),
    "options-sfx-button-listener": BaselineTaskSpec(
        "options-sfx-button-listener", "simple",
        "The sound-effects volume button in the options UI does nothing, while the other option buttons work. Locate the missing behavior, make the smallest repair, and validate it.",
        "Assets/Scripts/UI/OptionUI.cs", ("Assets/Scripts/UI/OptionUI.cs", "Assets/Scripts/SoundManager.cs"),
        _t5_inject, _t5_oracle,
    ),
    "delivery-result-subscription": BaselineTaskSpec(
        "delivery-result-subscription", "medium",
        "Deliveries are scored, but neither the success nor failure result popup appears. Locate the broken event chain, make the smallest repair, and validate it.",
        "Assets/Scripts/UI/DeliveryResultUI.cs", ("Assets/Scripts/UI/DeliveryResultUI.cs", "Assets/Scripts/DeliveryManager.cs", "Assets/Scripts/Counters/DeliveryCounter.cs"),
        _t2_inject, _t2_oracle,
    ),
    "plates-scriptableobject-reference": BaselineTaskSpec(
        "plates-scriptableobject-reference", "medium",
        "The plates counter spawns bread instead of plates. Locate the incorrect serialized reference in the prefab, make the smallest repair, and validate it.",
        "Assets/Prefabs/Counters/PlatesCounter.prefab", ("Assets/Prefabs/Counters/PlatesCounter.prefab", "Assets/Scripts/Counters/PlatesCounter.cs"),
        _asset_inject("plates-scriptableobject-reference"), _asset_oracle("plates-scriptableobject-reference"),
    ),
    "stove-progress-reference": BaselineTaskSpec(
        "stove-progress-reference", "hard",
        "The stove cooks food, but its progress bar never updates and reports that IHasProgress is missing. Locate the incorrect prefab reference, make the smallest repair, and validate it.",
        "Assets/Prefabs/Counters/StoveCounter.prefab", ("Assets/Prefabs/Counters/StoveCounter.prefab", "Assets/Scripts/UI/ProgressBarUI.cs", "Assets/Scripts/Counters/StoveCounter.cs", "Assets/Scripts/IHasProgress.cs"),
        _asset_inject("stove-progress-reference"), _asset_oracle("stove-progress-reference"),
    ),
    "stove-visual-component": BaselineTaskSpec(
        "stove-visual-component", "hard",
        "The stove state changes and cooking continues, but its visual state and particles never update. Locate the missing prefab component and references, repair them, and validate the result.",
        "Assets/Prefabs/Counters/StoveCounter.prefab", ("Assets/Prefabs/Counters/StoveCounter.prefab", "Assets/Scripts/Counters/StoveCounterVisual.cs", "Assets/Scripts/Counters/StoveCounter.cs"),
        _asset_inject("stove-visual-component"), _asset_oracle("stove-visual-component"),
    ),
}


def get_task(task_id: str) -> BaselineTaskSpec:
    try:
        return TASKS[task_id]
    except KeyError as exc:
        raise ValueError(f"Unknown Kitchen Chaos baseline task: {task_id}") from exc
