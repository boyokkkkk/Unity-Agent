import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from game_agent.api.app import create_app
from game_agent.persistence import Database
from game_agent.services import RunManager
from game_agent.services.worker import _capture_diff


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

    def test_event_ingestion_retries_an_incomplete_jsonl_line(self):
        manager = self.manager()
        run_id = "partial-event"
        artifact_dir = self.root / "artifacts" / run_id
        artifact_dir.mkdir(parents=True)
        manager.database.create_run({
            "run_id": run_id,
            "task": "partial",
            "status": "running",
            "config_path": str(self.config),
            "project_path": str(self.project),
            "artifact_dir": str(artifact_dir),
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        events_path = artifact_dir / "events.jsonl"
        partial = '{"run_id":"partial-event","seq":1,"event":"tool_end"'
        events_path.write_text(partial, encoding="utf-8")

        offset = manager._ingest_events(run_id, events_path, 0)
        self.assertEqual(offset, 0)
        self.assertEqual(manager.events(run_id), [])

        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(',"returncode":0}\n')
        offset = manager._ingest_events(run_id, events_path, offset)

        self.assertEqual(offset, events_path.stat().st_size)
        self.assertEqual([event["event"] for event in manager.events(run_id)], ["tool_end"])
        manager.shutdown()

    def test_workspace_claim_is_atomic_across_managers(self):
        first = self.manager(slow_worker)
        second = RunManager(
            Database(self.root / "runs.db"),
            self.root / "artifacts",
            worker_target=slow_worker,
            poll_interval=0.02,
        )
        barrier = threading.Barrier(2)
        first._assert_workspace_available = lambda _: barrier.wait(timeout=5)
        second._assert_workspace_available = lambda _: barrier.wait(timeout=5)
        created: list[tuple[RunManager, dict]] = []
        errors: list[Exception] = []

        def claim(manager: RunManager) -> None:
            try:
                created.append((manager, manager.create(task="claim", config_path=self.config)))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=claim, args=(manager,)) for manager in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        try:
            self.assertEqual(len(created), 1)
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], RuntimeError)
        finally:
            for manager, run in created:
                manager.cancel(run["run_id"])
            first.shutdown()
            second.shutdown()

    def test_capture_diff_includes_untracked_files(self):
        repository = self.root / "repository"
        repository.mkdir()
        subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
        tracked = repository / "tracked.txt"
        tracked.write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repository, check=True, capture_output=True)
        tracked.write_text("after\n", encoding="utf-8")
        (repository / "untracked.txt").write_text("new\n", encoding="utf-8")
        destination = self.root / "diff.patch"

        _capture_diff(repository, destination)
        patch = destination.read_text(encoding="utf-8")

        self.assertIn("tracked.txt", patch)
        self.assertIn("+after", patch)
        self.assertIn("untracked.txt", patch)
        self.assertIn("+new", patch)

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
            self.assertIn("event: run_event", event_stream.text)
            self.assertIn("id:", event_stream.text)
            data_lines = [
                json.loads(line.removeprefix("data: "))
                for line in event_stream.text.splitlines()
                if line.startswith("data: ")
            ]
            self.assertIn("run_start", [item["event"] for item in data_lines])
            self.assertTrue(all({"id", "event", "created_at", "data"} <= set(item) for item in data_lines))
            cursor = history[1]["id"]
            resumed = client.get(
                f"/api/runs/{run_id}/events?after=0",
                headers={"Last-Event-ID": str(cursor)},
            )
            resumed_items = [
                json.loads(line.removeprefix("data: "))
                for line in resumed.text.splitlines()
                if line.startswith("data: ")
            ]
            self.assertTrue(resumed_items)
            self.assertTrue(all(item["id"] > cursor for item in resumed_items))


if __name__ == "__main__":
    unittest.main()
