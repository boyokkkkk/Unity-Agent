from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

from .logging import ExperimentLogger
from .tools import WorkspaceTools


class BaselineRunner:
    def __init__(self, root: Path, config: dict) -> None:
        self.root = root.resolve()
        self.config = config
        run_id = uuid.uuid4().hex[:12]
        log_path = self.root / config["logging"]["path"]
        self.logger = ExperimentLogger(log_path, run_id=run_id, config_id=config["experiment"]["config_id"])
        self.tools = WorkspaceTools(self.root, self.logger)

    def compile(self) -> bool:
        command = self.config["commands"]["compile"]
        result = self.tools.run(command)
        passed = result.returncode == 0
        self.logger.emit("validation", validator="compile", status="passed" if passed else "failed")
        return passed

    def test(self, task_id: str) -> bool:
        command = [*self.config["commands"]["test"], task_id]
        result = self.tools.run(command)
        passed = result.returncode == 0
        self.logger.emit("validation", validator="test", status="passed" if passed else "failed")
        return passed

    def unity_probe(self) -> str:
        unity = self.config["commands"].get("unity")
        if not unity or shutil.which(unity[0]) is None:
            self.logger.emit("validation", validator="unity_playmode", status="skipped_unavailable")
            return "skipped_unavailable"
        result = self.tools.run(unity)
        status = "passed" if result.returncode == 0 else "failed"
        self.logger.emit("validation", validator="unity_playmode", status=status)
        return status

    def task(self, task_id: str) -> bool:
        tasks = {item["id"]: item for item in self.config["tasks"]}
        task = tasks[task_id]
        self.logger.emit("task_start", task_id=task_id, intent=task["intent"])
        for operation in task["operations"]:
            content = self.tools.read_file(operation["path"])
            updated = content.replace(operation["old"], operation["new"], 1)
            if content == updated:
                if operation["new"] not in content:
                    self.logger.emit("task_end", task_id=task_id, status="failed", reason="replacement_not_found")
                    return False
                self.logger.emit("tool", tool="write_file", path=operation["path"], status="already_applied")
            else:
                self.tools.write_file(operation["path"], updated)
        compile_ok = self.compile()
        test_ok = self.test(task_id) if compile_ok else False
        passed = compile_ok and test_ok
        self.logger.emit("task_end", task_id=task_id, status="passed" if passed else "failed",
                         compile=compile_ok, test=test_ok)
        return passed

    def run_all(self) -> int:
        results = {task["id"]: self.task(task["id"]) for task in self.config["tasks"]}
        summary = {"tasks": results, "all_passed": all(results.values()), "unity": self.unity_probe()}
        output = self.root / self.config["logging"]["summary"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0 if summary["all_passed"] else 1
