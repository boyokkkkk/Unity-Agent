from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import tempfile
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game_agent.baseline import StageAnalyzer, project_conversation
from game_agent.baseline_tasks import get_task
from game_agent.logging import ExperimentLogger
from game_agent.mini import load_config, run as run_agent
from game_agent.services.worker import _capture_diff, capture_task_baseline
from game_agent.validation import UnityValidator
from game_agent.workspace import WorkspaceLease, create_task_workspace


BASELINE_SCHEMA_VERSION = "game-agent-state-event-baseline-v1"
DEFAULT_TASK = (
    "玩家在开始界面按下交互键后，游戏应进入倒计时；目前教程界面没有关闭，"
    "倒计时界面也没有出现。问题可能位于游戏状态切换与 UI 刷新链路。"
    "请定位根因，进行最小修复，并通过相关 Unity 测试验证。"
)
ENGLISH_TASK = (
    "After the player presses the interact key on the start screen, the game should enter the "
    "countdown state. Currently the tutorial UI does not close and the countdown UI does not "
    "appear. The defect is likely in the interaction input, game-state transition, OnStateChanged "
    "event publication, or UI observer refresh chain. Locate the root cause, make the smallest "
    "possible repair, and validate it with the relevant Unity tests."
)
TARGET_SCRIPT = Path("Assets/Scripts/KitchenGameManager.cs")
RELEVANT_FILES = (
    "Assets/Scripts/KitchenGameManager.cs",
    "Assets/Scripts/UI/TutorialUI.cs",
    "Assets/Scripts/UI/GameStartCountdownUI.cs",
)
EVENT_STATEMENT = "OnStateChanged?.Invoke(this, EventArgs.Empty);"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _project_snapshot(project: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    roots = [project / "Assets", project / "Packages", project / "ProjectSettings"]
    for root in roots:
        if not root.exists():
            continue
        for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
            relative = path.relative_to(project).as_posix()
            snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _snapshot_fingerprint(snapshot: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative, file_digest in sorted(snapshot.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _project_fingerprint(project: Path) -> str:
    return _snapshot_fingerprint(_project_snapshot(project))


def _interaction_method(text: str) -> re.Match[str] | None:
    return re.search(
        r"private\s+void\s+GameInput_OnInteraction\s*\([^)]*\)\s*\{(?P<body>.*?)\n\s*\}",
        text,
        re.DOTALL,
    )


def inject_state_event_defect(project: Path, artifact_dir: Path) -> dict[str, Any]:
    target = project / TARGET_SCRIPT
    source = target.read_text(encoding="utf-8")
    method = _interaction_method(source)
    if method is None:
        raise ValueError("GameInput_OnInteraction method was not found")
    body = method.group("body")
    if "state = State.CountdownToStart;" not in body or body.count(EVENT_STATEMENT) != 1:
        raise ValueError("Expected one countdown state event statement in GameInput_OnInteraction")
    defective_body = body.replace(EVENT_STATEMENT, "", 1)
    defective = source[: method.start("body")] + defective_body + source[method.end("body") :]
    if defective == source:
        raise ValueError("Defect injection did not change the target script")
    target.write_text(defective, encoding="utf-8")

    patch = "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            defective.splitlines(keepends=True),
            fromfile=TARGET_SCRIPT.as_posix(),
            tofile=TARGET_SCRIPT.as_posix(),
        )
    )
    (artifact_dir / "defect.patch").write_text(patch, encoding="utf-8")
    manifest = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "target": TARGET_SCRIPT.as_posix(),
        "removed_statement": EVENT_STATEMENT,
        "source_sha256": _sha256_text(source),
        "defective_sha256": _sha256_text(defective),
        "replacement_count": 1,
        "patch": "defect.patch",
    }
    _write_json(artifact_dir / "defect-manifest.json", manifest)
    return manifest


def patch_matches_oracle(project: Path) -> bool:
    text = (project / TARGET_SCRIPT).read_text(encoding="utf-8")
    method = _interaction_method(text)
    if method is None:
        return False
    body = method.group("body")
    countdown = body.find("state = State.CountdownToStart;")
    event = body.find(EVENT_STATEMENT)
    return countdown >= 0 and event > countdown and "state = State.GamePlaying;" not in body


def _meta_guid(relative: str) -> str:
    return hashlib.sha256(("state-event-v1:" + relative).encode("utf-8")).hexdigest()[:32]


def _write_meta(target: Path, project: Path, *, folder: bool = False) -> None:
    relative = target.relative_to(project).as_posix()
    destination = Path(str(target) + ".meta")
    importer = "folderAsset: yes\nDefaultImporter:" if folder else "DefaultImporter:"
    destination.write_text(
        f"fileFormatVersion: 2\nguid: {_meta_guid(relative)}\n{importer}\n"
        "  externalObjects: {}\n  userData:\n  assetBundleName:\n  assetBundleVariant:\n",
        encoding="utf-8",
    )


EDITMODE_ORACLE = r"""using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class StateEventBaselineEditModeOracle
{
    [Test]
    public void WaitingInteraction_EntersCountdownAndPublishesOneStateEvent()
    {
        var type = Type.GetType("KitchenGameManager, Assembly-CSharp");
        Assert.That(type, Is.Not.Null);
        var gameObject = new GameObject("StateEventBaseline-EditMode");
        var behaviour = (MonoBehaviour)gameObject.AddComponent(type);
        behaviour.enabled = false;

        var eventInfo = type.GetEvent("OnStateChanged", BindingFlags.Instance | BindingFlags.Public);
        var interaction = type.GetMethod("GameInput_OnInteraction", BindingFlags.Instance | BindingFlags.NonPublic);
        var isCountdown = type.GetMethod("IsCountdownToStartActive", BindingFlags.Instance | BindingFlags.Public);
        var isPlaying = type.GetMethod("IsGamePlaying", BindingFlags.Instance | BindingFlags.Public);
        Assert.That(eventInfo, Is.Not.Null);
        Assert.That(interaction, Is.Not.Null);

        var notifications = 0;
        EventHandler handler = (_, __) => notifications++;
        eventInfo.AddEventHandler(behaviour, handler);
        interaction.Invoke(behaviour, new object[] { null, EventArgs.Empty });

        Assert.That((bool)isCountdown.Invoke(behaviour, null), Is.True);
        Assert.That((bool)isPlaying.Invoke(behaviour, null), Is.False);
        Assert.That(notifications, Is.EqualTo(1));
        UnityEngine.Object.DestroyImmediate(gameObject);
    }
}
"""


PLAYMODE_ORACLE = r"""using System;
using System.Collections;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

public class StateEventBaselinePlayModeOracle
{
    [UnityTest]
    public IEnumerator WaitingInteraction_UpdatesObservableStateWithoutSkippingCountdown()
    {
        var type = Type.GetType("KitchenGameManager, Assembly-CSharp");
        Assert.That(type, Is.Not.Null);
        var gameObject = new GameObject("StateEventBaseline-PlayMode");
        var behaviour = (MonoBehaviour)gameObject.AddComponent(type);
        behaviour.enabled = false;

        var eventInfo = type.GetEvent("OnStateChanged", BindingFlags.Instance | BindingFlags.Public);
        var interaction = type.GetMethod("GameInput_OnInteraction", BindingFlags.Instance | BindingFlags.NonPublic);
        var isCountdown = type.GetMethod("IsCountdownToStartActive", BindingFlags.Instance | BindingFlags.Public);
        var isPlaying = type.GetMethod("IsGamePlaying", BindingFlags.Instance | BindingFlags.Public);
        var notifications = 0;
        EventHandler handler = (_, __) => notifications++;
        eventInfo.AddEventHandler(behaviour, handler);

        interaction.Invoke(behaviour, new object[] { null, EventArgs.Empty });

        Assert.That((bool)isCountdown.Invoke(behaviour, null), Is.True);
        Assert.That((bool)isPlaying.Invoke(behaviour, null), Is.False);
        Assert.That(notifications, Is.EqualTo(1));
        UnityEngine.Object.Destroy(gameObject);
        yield return null;
    }
}
"""


EDITMODE_ASMDEF = {
    "name": "KitchenChaos.BaselineOracle.EditMode",
    "references": [],
    "includePlatforms": ["Editor"],
    "excludePlatforms": [],
    "allowUnsafeCode": False,
    "overrideReferences": False,
    "precompiledReferences": [],
    "autoReferenced": True,
    "defineConstraints": [],
    "versionDefines": [],
    "noEngineReferences": False,
    "optionalUnityReferences": ["TestAssemblies"],
}
PLAYMODE_ASMDEF = {**EDITMODE_ASMDEF, "name": "KitchenChaos.BaselineOracle.PlayMode", "includePlatforms": []}


def inject_hidden_oracle(project: Path, artifact_dir: Path) -> dict[str, Any]:
    root = project / "Assets" / "Tests" / "BaselineOracle"
    if root.exists() or Path(str(root) + ".meta").exists():
        raise FileExistsError(f"Hidden oracle path already exists: {root}")
    edit = root / "EditMode"
    play = root / "PlayMode"
    edit.mkdir(parents=True)
    play.mkdir()
    files = {
        edit / "KitchenChaos.BaselineOracle.EditMode.asmdef": json.dumps(
            EDITMODE_ASMDEF, ensure_ascii=False, indent=2
        ),
        edit / "StateEventBaselineEditModeOracle.cs": EDITMODE_ORACLE,
        play / "KitchenChaos.BaselineOracle.PlayMode.asmdef": json.dumps(
            PLAYMODE_ASMDEF, ensure_ascii=False, indent=2
        ),
        play / "StateEventBaselinePlayModeOracle.cs": PLAYMODE_ORACLE,
    }
    for directory in (root, edit, play):
        _write_meta(directory, project, folder=True)
    for path, content in files.items():
        path.write_text(content + ("" if content.endswith("\n") else "\n"), encoding="utf-8")
        _write_meta(path, project)
    manifest = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "root": root.relative_to(project).as_posix(),
        "files": {
            path.relative_to(project).as_posix(): _sha256_text(path.read_text(encoding="utf-8"))
            for path in files
        },
        "visible_to_agent": False,
    }
    _write_json(artifact_dir / "oracle-manifest.json", manifest)
    return manifest


def remove_hidden_oracle(project: Path) -> bool:
    root = project / "Assets" / "Tests" / "BaselineOracle"
    meta = Path(str(root) + ".meta")
    if root.exists():
        shutil.rmtree(root)
    if meta.exists():
        meta.unlink()
    return not root.exists() and not meta.exists()


class ArtifactEventAppender:
    def __init__(self, path: Path, *, run_id: str, config_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self.config_id = config_id
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ] if path.is_file() else []
        self.sequence = max((int(item.get("seq", 0)) for item in records), default=0)
        self.base_elapsed = max((int(item.get("elapsed_ms", 0)) for item in records), default=0)
        self.started = time.perf_counter()

    def emit(self, event: str, **data: Any) -> dict[str, Any]:
        self.sequence += 1
        default_component, default_phase = ExperimentLogger.EVENT_PHASES.get(event, ("run", "event"))
        record = {
            "schema_version": "game-agent-jsonl-v3",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "monotonic_ns": time.perf_counter_ns(),
            "elapsed_ms": self.base_elapsed + int((time.perf_counter() - self.started) * 1000),
            "run_id": self.run_id,
            "config_id": self.config_id,
            "seq": self.sequence,
            "event": event,
            "component": data.pop("component", default_component),
            "phase": data.pop("phase", default_phase),
            "turn": int(data.pop("turn", 1) or 0),
            "round": int(data.pop("round", 0) or 0),
            **data,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record


@dataclass(frozen=True)
class BaselineCase:
    source_project: Path
    config_path: Path
    artifact_dir: Path
    editor_path: Path
    task: str = DEFAULT_TASK
    variant: str = "baseline"
    isolation: str = "copy"
    keep_workspace: bool = False
    task_id: str = "state-event-publication"
    workspace_root: Path | None = None


class StateEventBaselineRunner:
    def __init__(
        self,
        case: BaselineCase,
        *,
        agent_runner: Callable[..., dict[str, Any]] = run_agent,
        validator_factory: Callable[..., UnityValidator] = UnityValidator,
    ) -> None:
        self.case = case
        self.agent_runner = agent_runner
        self.validator_factory = validator_factory
        self.task_spec = get_task(case.task_id)

    def _prepare_config(self, project: Path, run_id: str) -> tuple[dict[str, Any], Path]:
        config = json.loads(json.dumps(load_config(self.case.config_path)))
        if self.case.variant not in {"baseline", "innovation"}:
            raise ValueError(f"Unsupported experiment variant: {self.case.variant}")
        innovation_enabled = self.case.variant == "innovation"
        ablation_group = str(config.get("ablation_group", "")).strip()
        config["experiment"]["config_id"] = (
            f"state-event-v1-{ablation_group}"
            if innovation_enabled and ablation_group else
            "state-event-v1-innovation" if innovation_enabled else "state-event-v1-no-skill"
        )
        config["experiment"]["target_project"] = str(project)
        config["environment"]["cwd"] = str(project)
        config.setdefault("skills", {})
        if innovation_enabled:
            config["skills"].setdefault("enabled", True)
        else:
            config["skills"]["enabled"] = False
        config["skills"]["paths"] = []
        config.setdefault("context", {})
        if innovation_enabled:
            config["context"].setdefault("enabled", True)
        else:
            config["context"]["enabled"] = False
        configured_graph = str(config["context"].get("graph_path", "")).strip()
        configured_graph_sha = str(config["context"].get("graph_sha256", "")).strip().casefold()
        resolved_graph: Path | None = None
        if innovation_enabled and configured_graph:
            resolved_graph = Path(configured_graph)
            if not resolved_graph.is_absolute():
                repository_root = Path(__file__).resolve().parents[2]
                resolved_graph = repository_root / resolved_graph
            resolved_graph = resolved_graph.resolve()
            if not resolved_graph.is_file():
                raise FileNotFoundError(f"Configured project graph does not exist: {resolved_graph}")
            actual_graph_sha = hashlib.sha256(resolved_graph.read_bytes()).hexdigest()
            if configured_graph_sha and actual_graph_sha.casefold() != configured_graph_sha:
                raise ValueError(
                    "Configured project graph SHA-256 does not match context.graph_sha256: "
                    f"expected {configured_graph_sha}, observed {actual_graph_sha}"
                )
            config["context"]["graph_sha256"] = actual_graph_sha
        if innovation_enabled and config["context"].get("enabled", False):
            if not configured_graph:
                raise ValueError("Innovation variant requires context.graph_path")
            assert resolved_graph is not None
            config["context"]["graph_path"] = str(resolved_graph)
        else:
            config["context"]["graph_path"] = ""
        config.setdefault("aci", {})
        if innovation_enabled:
            config["aci"].setdefault("enabled", True)
            config["aci"].setdefault("typed_mutations_enabled", True)
        else:
            config["aci"]["enabled"] = False
            config["aci"]["typed_mutations_enabled"] = False
        config["aci"]["editor_path"] = str(self.case.editor_path.resolve())
        config.setdefault("model", {})
        if innovation_enabled:
            config["model"].setdefault("structured_query_tools_enabled", True)
        else:
            config["model"]["structured_query_tools_enabled"] = False
        config.setdefault("validation", {})
        config["validation"]["enabled"] = False
        config["validation"]["editor_path"] = str(self.case.editor_path.resolve())
        config["logging"]["events_path"] = str(self.case.artifact_dir / "events.jsonl")
        config["logging"]["trajectory_path"] = str(self.case.artifact_dir / "trajectory.json")
        destination = self.case.artifact_dir / "config.json"
        _write_json(destination, config)
        _write_json(
            self.case.artifact_dir / "case.json",
            {
                "schema_version": BASELINE_SCHEMA_VERSION,
                "run_id": run_id,
                "variant": self.case.variant,
                "ablation_group": ablation_group,
                "task": self.case.task,
                "task_id": self.task_spec.id,
                "task_difficulty": self.task_spec.difficulty,
                "source_project": str(self.case.source_project.resolve()),
                "project_path": str(project),
                "isolation": self.case.isolation,
                "skills_enabled": bool(config["skills"].get("enabled")),
                "context_virtualization_enabled": bool(config["context"].get("enabled")),
                "structured_query_tools_enabled": bool(config["model"].get("structured_query_tools_enabled")),
                "typed_mutation_tools_enabled": bool(config["aci"].get("typed_mutations_enabled")),
                "graph_path": config["context"].get("graph_path", ""),
                "editor_path": str(self.case.editor_path.resolve()),
            },
        )
        return config, destination

    @staticmethod
    def _treatment_activation(
        config: dict[str, Any], events: list[dict[str, Any]]
    ) -> tuple[bool, dict[str, Any]]:
        condition = str(config.get("context_condition", "")).upper()
        if condition not in {"C0", "C1", "C2", "C3", "C4"}:
            return True, {"condition": condition or "legacy", "checked": False}
        treatment_events = [
            item for item in events
            if item.get("event") in {"context_retrieval_treatment", "context_assembled"}
            and isinstance(item.get("treatment"), dict)
        ]
        latest = treatment_events[-1]["treatment"] if treatment_events else {}
        retrieval = latest.get("retrieval", {}) if isinstance(latest, dict) else {}
        retrieval_last = latest.get("retrieval_last", {}) if isinstance(latest, dict) else {}
        assembled = sum(1 for item in events if item.get("event") == "context_assembled")
        bypassed = sum(1 for item in events if item.get("event") == "context_assembly_bypassed")
        graph_scores = int(retrieval.get("graph_score_contributions", 0) or 0)
        semantic_scores = int(retrieval.get("semantic_score_contributions", 0) or 0)
        source_causal = int(retrieval.get("source_causal_edges", 0) or 0)
        returned_causal = int(retrieval.get("returned_causal_edges", 0) or 0)
        suppressed_causal = int(retrieval.get("suppressed_causal_edges", 0) or 0)
        noncausal = int(retrieval.get("noncausal_graph_candidates", 0) or 0)
        checks = {
            "C0": graph_scores > 0 and semantic_scores > 0 and returned_causal > 0 and assembled > 0,
            "C1": graph_scores == 0 and semantic_scores > 0 and assembled > 0,
            "C2": graph_scores > 0 and semantic_scores == 0 and assembled > 0,
            "C3": source_causal > 0 and returned_causal == 0 and suppressed_causal > 0 and noncausal > 0 and assembled > 0,
            "C4": graph_scores > 0 and bypassed > 0 and assembled == 0,
        }
        evidence = {
            "condition": condition,
            "checked": True,
            "activated": checks[condition],
            "graph_score_contributions": graph_scores,
            "semantic_score_contributions": semantic_scores,
            "semantic_status": str(retrieval_last.get("semantic_status", "")),
            "semantic_reason": str(retrieval_last.get("semantic_reason", "")),
            "semantic_model": str(retrieval_last.get("semantic_model", "")),
            "source_causal_edges": source_causal,
            "returned_causal_edges": returned_causal,
            "suppressed_causal_edges": suppressed_causal,
            "noncausal_graph_candidates": noncausal,
            "assembly_injections": assembled,
            "assembly_bypasses": bypassed,
        }
        return checks[condition], evidence

    @staticmethod
    def _validation_passed(summary: dict[str, Any], modes: tuple[str, ...]) -> bool:
        checks = {str(item.get("name")): item for item in summary.get("checks", [])}
        return summary.get("status") == "passed" and all(
            checks.get(mode, {}).get("status") == "passed" for mode in modes
        )

    def _validate(
        self,
        project: Path,
        destination: Path,
        modes: tuple[str, ...],
        event_sink: Callable[..., object],
        scope: str,
    ) -> dict[str, Any]:
        def scoped_sink(event: str, **data: Any) -> object:
            return event_sink(event, validation_scope=scope, **data)

        validator = self.validator_factory(
            project,
            destination,
            {
                "editor_path": str(self.case.editor_path),
                "modes": list(modes),
                "timeout_seconds": 1200,
            },
            event_sink=scoped_sink,
        )
        return validator.run()

    @staticmethod
    def _recommendation(metrics: dict[str, Any]) -> dict[str, str]:
        navigation = metrics.get("navigation", {})
        context = metrics.get("context", {})
        milestones = metrics.get("milestones_ms", {})
        if float(navigation.get("navigation_precision", 0.0)) < 0.5:
            return {
                "innovation": "unity_project_graph",
                "reason": "相关文件导航精度低，优先用 Scene/Component/C# 依赖图约束检索范围。",
            }
        if float(context.get("repeated_observation_ratio", 0.0)) >= 0.25:
            return {
                "innovation": "evidence_memory",
                "reason": "重复观测占比较高，优先实现证据记忆与上下文去重。",
            }
        if milestones.get("T5_first_correct_patch") is not None and milestones.get("T6_first_validation") is None:
            return {
                "innovation": "automatic_validation_loop",
                "reason": "已形成正确补丁但没有及时验证，优先实现自动验证闭环。",
            }
        return {
            "innovation": "evidence_backed_submission",
            "reason": "导航和上下文未形成主导缺口，优先强化最终声明与验证证据绑定。",
        }

    def run(self) -> dict[str, Any]:
        artifact_dir = self.case.artifact_dir.resolve()
        artifact_dir.mkdir(parents=True, exist_ok=False)
        run_id = artifact_dir.name or uuid.uuid4().hex[:12]
        source = self.case.source_project.resolve()
        source_snapshot_before = _project_snapshot(source)
        source_before = _snapshot_fingerprint(source_snapshot_before)
        lease: WorkspaceLease | None = None
        project: Path | None = None
        baseline = None
        agent_result: dict[str, Any] = {}
        public_validation: dict[str, Any] = {}
        hidden_validation: dict[str, Any] = {}
        oracle_cleanup = True
        infrastructure_errors: list[str] = []

        try:
            # Create workspace in temp directory, not in artifacts (avoid 1.6GB per experiment)
            workspace_parent = (
                self.case.workspace_root.resolve()
                if self.case.workspace_root is not None
                else Path(tempfile.gettempdir()) / "game-agent-baselines"
            )
            workspace_root = workspace_parent / run_id
            lease = create_task_workspace(source, workspace_root, mode=self.case.isolation)
            project = lease.project_path
            self.task_spec.inject(project, artifact_dir, self.case.editor_path)
            config, prepared_config = self._prepare_config(project, run_id)
            ablation_group = str(config.get("ablation_group", "")).strip()
            baseline = capture_task_baseline(
                project,
                artifact_dir / "workspace-baseline.json",
                exclude_paths=(artifact_dir,),
            )
            if baseline is None:
                raise RuntimeError("Unable to capture isolated workspace baseline")

            try:
                agent_result = self.agent_runner(self.case.task, prepared_config, run_id=run_id)
            except BaseException as exc:
                agent_result = {
                    "exit_status": type(exc).__name__,
                    "submission": "",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            _write_json(artifact_dir / "agent-result.json", agent_result)
            _capture_diff(project, artifact_dir / "diff.patch", baseline)

            appender = ArtifactEventAppender(
                artifact_dir / "events.jsonl",
                run_id=run_id,
                config_id=config["experiment"]["config_id"],
            )
            oracle_match = self.task_spec.oracle(project, self.case.editor_path)
            appender.emit(
                "diff_snapshot",
                component="environment",
                oracle_match=oracle_match,
                observed_post_run=True,
                patch_sha256=hashlib.sha256((artifact_dir / "diff.patch").read_bytes()).hexdigest(),
            )

            public_validation = self._validate(
                project,
                artifact_dir / "validation" / "public",
                ("compile", "editmode", "playmode"),
                appender.emit,
                "public",
            )
            if self.task_spec.id == "state-event-publication":
                inject_hidden_oracle(project, artifact_dir / "validation" / "hidden")
                try:
                    hidden_validation = self._validate(
                        project,
                        artifact_dir / "validation" / "hidden",
                        ("editmode", "playmode"),
                        appender.emit,
                        "hidden",
                    )
                finally:
                    oracle_cleanup = remove_hidden_oracle(project)
                    if not oracle_cleanup:
                        infrastructure_errors.append("hidden_oracle_cleanup_failed")
            else:
                hidden_validation = {
                    "status": "passed" if oracle_match else "failed",
                    "checks": [
                        {"name": "task_oracle", "status": "passed" if oracle_match else "failed"}
                    ],
                    "task_id": self.task_spec.id,
                    "oracle_kind": "task_specific",
                }
                _write_json(
                    artifact_dir / "validation" / "hidden" / "summary.json",
                    hidden_validation,
                )

            events = [
                json.loads(line)
                for line in (artifact_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            trajectory = (
                json.loads((artifact_dir / "trajectory.json").read_text(encoding="utf-8"))
                if (artifact_dir / "trajectory.json").is_file()
                else None
            )
            metrics = StageAnalyzer(
                relevant_files=self.task_spec.relevant_files,
                root_cause_file=self.task_spec.root_cause_file,
            ).analyze(events, trajectory=trajectory)
            _write_json(artifact_dir / "stage-metrics.json", metrics)
            conversation = project_conversation(events)
            with (artifact_dir / "conversation.jsonl").open("w", encoding="utf-8") as handle:
                for message in conversation:
                    handle.write(json.dumps(message, ensure_ascii=False, sort_keys=True) + "\n")

            source_snapshot_after = _project_snapshot(source)
            source_after = _snapshot_fingerprint(source_snapshot_after)
            source_unchanged = source_before == source_after
            source_changed_paths = sorted(
                path for path in set(source_snapshot_before) | set(source_snapshot_after)
                if source_snapshot_before.get(path) != source_snapshot_after.get(path)
            )
            if not source_unchanged:
                infrastructure_errors.append("source_project_changed")
            no_skill_evidence = config.get("skills", {}).get("enabled") is False and not any(
                item.get("event") in {"skill_matched", "skill_apply_start", "skill_apply_end"} for item in events
            )
            innovation_checks = [
                config.get("skills", {}).get("enabled") is True,
                config.get("model", {}).get("structured_query_tools_enabled") is True,
                config.get("aci", {}).get("enabled") is True,
            ]
            if not ablation_group:
                innovation_checks.extend((
                    config.get("context", {}).get("enabled") is True,
                    Path(str(config.get("context", {}).get("graph_path", ""))).is_file(),
                    config.get("aci", {}).get("typed_mutations_enabled") is True,
                ))
            innovation_config_evidence = all(innovation_checks)
            condition_evidence = (
                innovation_config_evidence if self.case.variant == "innovation" else no_skill_evidence
            )
            if not condition_evidence:
                infrastructure_errors.append(f"{self.case.variant}_condition_violated")
            treatment_activated, treatment_evidence = self._treatment_activation(config, events)
            if not treatment_activated:
                infrastructure_errors.append("treatment_not_activated")
            if not (artifact_dir / "events.jsonl").is_file():
                infrastructure_errors.append("events_missing")
            if not public_validation or not hidden_validation:
                infrastructure_errors.append("validation_missing")

            public_passed = self._validation_passed(
                public_validation, ("compile", "editmode", "playmode")
            )
            hidden_modes = (
                ("editmode", "playmode")
                if self.task_spec.id == "state-event-publication" else ("task_oracle",)
            )
            hidden_passed = self._validation_passed(hidden_validation, hidden_modes)
            agent_submitted = agent_result.get("exit_status") == "Submitted"
            verified_success = bool(agent_submitted and oracle_match and public_passed and hidden_passed)
            experiment_valid = not infrastructure_errors
            report = {
                "schema_version": BASELINE_SCHEMA_VERSION,
                "run_id": run_id,
                "variant": self.case.variant,
                "ablation_group": ablation_group,
                "task_id": self.task_spec.id,
                "task_difficulty": self.task_spec.difficulty,
                "experiment_valid": experiment_valid,
                "infrastructure_errors": infrastructure_errors,
                "source_project_unchanged": source_unchanged,
                "source_project_changed_paths": source_changed_paths,
                "hidden_oracle_cleaned": oracle_cleanup,
                "no_skill_evidence": no_skill_evidence,
                "innovation_config_evidence": innovation_config_evidence,
                "condition_evidence": condition_evidence,
                "treatment_activation": treatment_evidence,
                "agent": {
                    "submitted": agent_submitted,
                    "exit_status": agent_result.get("exit_status", ""),
                    "submission": agent_result.get("submission", ""),
                    "error": agent_result.get("error", ""),
                },
                "oracle_match": oracle_match,
                "public_validation_passed": public_passed,
                "hidden_validation_passed": hidden_passed,
                "verified_success": verified_success,
                "metrics": metrics,
                "recommended_innovation": self._recommendation(metrics),
                "artifacts": {
                    "events": "events.jsonl",
                    "conversation": "conversation.jsonl",
                    "trajectory": "trajectory.json",
                    "diff": "diff.patch",
                    "public_validation": "validation/public/summary.json",
                    "hidden_validation": "validation/hidden/summary.json",
                    "stage_metrics": "stage-metrics.json",
                },
            }
            _write_json(artifact_dir / "baseline-report.json", report)
            self._write_markdown_report(artifact_dir / "baseline-report.md", report)
            return report
        finally:
            if project is not None and not oracle_cleanup:
                try:
                    remove_hidden_oracle(project)
                except Exception:
                    pass
            if lease is not None and not self.case.keep_workspace:
                lease.close()

    @staticmethod
    def _write_markdown_report(path: Path, report: dict[str, Any]) -> None:
        metrics = report.get("metrics", {})
        navigation = metrics.get("navigation", {})
        context = metrics.get("context", {})
        behavior = metrics.get("behavior", {})
        recommendation = report.get("recommended_innovation", {})
        path.write_text(
            "# State-event baseline report\n\n"
            f"- Run: `{report.get('run_id', '')}`\n"
            f"- Experiment valid: `{report.get('experiment_valid')}`\n"
            f"- Agent exit: `{report.get('agent', {}).get('exit_status', '')}`\n"
            f"- Verified success: `{report.get('verified_success')}`\n"
            f"- Public validation: `{report.get('public_validation_passed')}`\n"
            f"- Hidden validation: `{report.get('hidden_validation_passed')}`\n"
            f"- Source unchanged: `{report.get('source_project_unchanged')}`\n\n"
            "## Metrics\n\n"
            f"- Total tokens: `{context.get('total_tokens', 0)}`\n"
            f"- Model calls: `{behavior.get('model_calls', 0)}`\n"
            f"- Tool calls: `{behavior.get('tool_calls', 0)}`\n"
            f"- Navigation precision: `{navigation.get('navigation_precision', 0.0):.4f}`\n"
            f"- Relevant recall: `{navigation.get('relevant_recall', 0.0):.4f}`\n"
            f"- Repeated observation ratio: `{context.get('repeated_observation_ratio', 0.0):.4f}`\n\n"
            "## Recommended innovation\n\n"
            f"- `{recommendation.get('innovation', '')}`: {recommendation.get('reason', '')}\n",
            encoding="utf-8",
        )
