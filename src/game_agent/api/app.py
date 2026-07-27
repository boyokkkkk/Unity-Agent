from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse

from game_agent.persistence import Database
from game_agent.services import RunManager
from game_agent.services.run_manager import TERMINAL_STATUSES

from .schemas import ArtifactInfo, RunCreate


def _default_data_dir() -> Path:
    return Path(os.getenv("GAME_AGENT_DATA_DIR", "artifacts"))


def create_app(*, data_dir: Path | None = None, manager: RunManager | None = None) -> FastAPI:
    root = Path.cwd().resolve()
    storage = (data_dir or _default_data_dir()).resolve()
    run_manager = manager or RunManager(Database(storage / "game-agent.db"), storage / "runs")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        run_manager.shutdown()

    app = FastAPI(title="SkillGameAgent API", version="0.3.0", lifespan=lifespan)
    app.state.run_manager = run_manager

    def get_run(run_id: str) -> dict:
        try:
            return run_manager.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/runs", status_code=status.HTTP_202_ACCEPTED)
    def create_run(body: RunCreate) -> dict:
        config_path = Path(body.config_path)
        if not config_path.is_absolute():
            config_path = root / config_path
        try:
            return run_manager.create(
                task=body.task,
                config_path=config_path,
                project_path=Path(body.project_path) if body.project_path else None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/runs")
    def list_runs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> list[dict]:
        return run_manager.list(limit=limit, offset=offset)

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict:
        return get_run(run_id)

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict:
        get_run(run_id)
        return run_manager.cancel(run_id)

    @app.get("/api/runs/{run_id}/events/history")
    def event_history(run_id: str, after: int = Query(0, ge=0)) -> list[dict]:
        get_run(run_id)
        return run_manager.events(run_id, after_id=after)

    @app.get("/api/runs/{run_id}/events")
    async def stream_events(
        run_id: str,
        request: Request,
        after: int = Query(0, ge=0),
        last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        get_run(run_id)
        try:
            cursor = max(after, int(last_event_id or 0))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc

        async def generate() -> AsyncIterator[str]:
            nonlocal cursor
            idle_ticks = 0
            while not await request.is_disconnected():
                events = run_manager.events(run_id, after_id=cursor)
                if events:
                    idle_ticks = 0
                    for item in events:
                        cursor = item["id"]
                        data = json.dumps(item, ensure_ascii=False)
                        yield f"id: {cursor}\nevent: run_event\ndata: {data}\n\n"
                else:
                    idle_ticks += 1
                    current = run_manager.get(run_id)
                    if current["status"] in TERMINAL_STATUSES and idle_ticks >= 2:
                        break
                    if idle_ticks % 20 == 0:
                        yield ": keep-alive\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(
            generate(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/trajectory")
    def trajectory(run_id: str):
        get_run(run_id)
        try:
            path = run_manager.artifact_path(run_id, "trajectory.json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Trajectory is not available yet") from exc
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/runs/{run_id}/diff")
    def diff(run_id: str):
        get_run(run_id)
        try:
            path = run_manager.artifact_path(run_id, "diff.patch")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Diff is not available yet") from exc
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/x-diff")

    @app.get("/api/runs/{run_id}/artifacts", response_model=list[ArtifactInfo])
    def artifacts(run_id: str) -> list[dict]:
        get_run(run_id)
        return [{
            "name": item["name"], "size": item["size"], "created_at": item["created_at"],
            "download_url": f"/api/runs/{run_id}/artifacts/{item['name']}",
        } for item in run_manager.artifacts(run_id)]

    @app.get("/api/runs/{run_id}/artifacts/{name:path}")
    def download_artifact(run_id: str, name: str):
        get_run(run_id)
        try:
            path = run_manager.artifact_path(run_id, name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc
        return FileResponse(path, filename=path.name)

    return app


app = create_app()
