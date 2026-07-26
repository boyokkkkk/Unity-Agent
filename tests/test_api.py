import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from game_agent.api.app import create_app
from game_agent.persistence import Database
from game_agent.services import RunManager


def fixture_worker(run_id: str, task: str, config_path: str, project_path: str, artifact_dir: str) -> None:
    root = Path(artifact_dir)
    root.mkdir(parents=True, exist_ok=True)
    events = [
        {"run_id": run_id, "seq": 1, "event": "run_start", "task": task},
        {"run_id": run_id, "seq": 2, "event": "run_end", "exit_status": "Submitted"},
    ]
    (root / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    (root / "trajectory.json").write_text(
        json.dumps({"messages": [], "info": {"run_id": run_id}}), encoding="utf-8"
    )
    (root / "diff.patch").write_text("diff --git a/A.cs b/A.cs\n", encoding="utf-8")
    (root / "result.json").write_text(json.dumps({
        "run_id": run_id, "status": "submitted", "exit_status": "Submitted", "submission": "done",
    }), encoding="utf-8")


def slow_worker(run_id: str, task: str, config_path: str, project_path: str, artifact_dir: str) -> None:
    time.sleep(30)


def wait_for_terminal(manager: RunManager, run_id: str, timeout: float = 5) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = manager.get(run_id)
        if current["status"] in {"submitted", "failed", "cancelled", "timed_out"}:
            return current
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} did not finish")


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "UnityProject"
        (self.project / "ProjectSettings").mkdir(parents=True)
        (self.project / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: test")
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({
            "experiment": {
                "config_id": "test", "backend": "fixture", "target_project": str(self.project),
                "tool": "bash", "max_input_tokens": 100, "max_output_tokens": 100,
                "max_total_tokens": 100, "max_rounds": 2, "cost_limit": 1,
            },
            "model": {"model_name": "fixture"},
            "environment": {"cwd": str(self.project)},
            "agent": {
                "system_template": "test", "instance_template": "{{ task }}",
                "step_limit": 2, "cost_limit": 1,
            },
            "logging": {"events_path": "unused", "trajectory_path": "unused"},
        }), encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def manager(self, worker=fixture_worker) -> RunManager:
        return RunManager(Database(self.root / "runs.db"), self.root / "artifacts",
                          worker_target=worker, poll_interval=0.02)

    def test_manager_runs_worker_persists_events_and_indexes_artifacts(self):
        manager = self.manager()
        created = manager.create(task="fixture", config_path=self.config)
        finished = wait_for_terminal(manager, created["run_id"])

        self.assertEqual(finished["status"], "submitted")
        self.assertEqual(finished["submission"], "done")
        self.assertIn("run_start", [event["event"] for event in manager.events(created["run_id"])])
        self.assertIn("trajectory.json", [item["name"] for item in manager.artifacts(created["run_id"])])
        with self.assertRaises(ValueError):
            manager.artifact_path(created["run_id"], "../runs.db")
        manager.shutdown()

    def test_manager_cancels_worker(self):
        manager = self.manager(slow_worker)
        created = manager.create(task="wait", config_path=self.config)
        cancelled = manager.cancel(created["run_id"])

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["exit_status"], "Cancelled")
        self.assertIn("run_cancelled", [event["event"] for event in manager.events(created["run_id"])])
        manager.shutdown()

    def test_run_artifact_and_sse_api(self):
        manager = self.manager()
        app = create_app(data_dir=self.root / "api", manager=manager)
        with TestClient(app) as client:
            response = client.post("/api/runs", json={
                "task": "fixture", "config_path": str(self.config), "project_path": str(self.project),
            })
            self.assertEqual(response.status_code, 202)
            run_id = response.json()["run_id"]
            wait_for_terminal(manager, run_id)

            self.assertEqual(client.get(f"/api/runs/{run_id}").json()["status"], "submitted")
            self.assertEqual(client.get(f"/api/runs/{run_id}/trajectory").status_code, 200)
            self.assertIn("diff --git", client.get(f"/api/runs/{run_id}/diff").text)
            artifacts = client.get(f"/api/runs/{run_id}/artifacts").json()
            self.assertIn("result.json", [item["name"] for item in artifacts])
            history = client.get(f"/api/runs/{run_id}/events/history").json()
            self.assertIn("run_start", [event["event"] for event in history])
            event_stream = client.get(f"/api/runs/{run_id}/events")
            self.assertIn("event: run_start", event_stream.text)
            self.assertIn("id:", event_stream.text)


if __name__ == "__main__":
    unittest.main()
