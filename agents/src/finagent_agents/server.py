"""HTTP API for running workflows: catalog, start, live events (SSE), cancel.

Only live state is served here. Run history is read from the data API, where every run is
saved at start and end.
"""

import json
import logging
import secrets
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from finagent_agents.config import AgentSettings
from finagent_agents.context import MakeLLM
from finagent_agents.data import DataLayer, HttpDataLayer, MemoryDataLayer
from finagent_agents.events import Event, EventHub
from finagent_agents.registry import InputError, Workflow, WorkflowError, load_workflows
from finagent_agents.runner import Runner, mark_interrupted

log = logging.getLogger(__name__)

KEEPALIVE_S = 15.0  # SSE comment ping during silence; keeps proxies from closing the stream
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
# Browsers label requests from other sites; the proxies add tokens, so refuse those outright.
CROSS_SITE = {"cross-site", "same-site"}


class WorkflowInfo(BaseModel):
    name: str
    graph: str
    input: dict[str, str]  # field -> type: str | int | float | bool | list[str]
    nodes: dict[str, dict]  # node -> {model, effort, prompt, tools}
    timeout_s: float
    max_concurrency: int
    schedule: str | None = None


class StartRun(BaseModel):
    inputs: dict = {}


class RunStarted(BaseModel):
    run_id: str
    workflow: str
    status: str
    started_at: datetime


def _info(wf: Workflow) -> WorkflowInfo:
    return WorkflowInfo(
        name=wf.name,
        graph=wf.graph,
        input=wf.input,
        nodes=wf.describe(),
        timeout_s=wf.timeout_s,
        max_concurrency=wf.max_concurrency,
        schedule=wf.schedule,
    )


def _sse(event: Event | None) -> str:
    if event is None:
        return ": keepalive\n\n"
    return f"id: {event.id}\nevent: {event.type}\ndata: {json.dumps(event.data, default=str)}\n\n"


def create_app(
    settings: AgentSettings | None = None,
    workflows: dict[str, Workflow] | None = None,
    data: DataLayer | None = None,
    make_llm: MakeLLM | None = None,
    keepalive: float = KEEPALIVE_S,
) -> FastAPI:
    """`data`/`make_llm` default to the configured data API (or memory) and Claude; tests
    pass fakes."""
    settings = settings or AgentSettings()
    if workflows is None:
        workflows = load_workflows(settings.workflows_file, settings.prompts_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = None
        store = data
        if store is None:
            if settings.data_url:
                store = owned = HttpDataLayer(settings.data_url, settings.data_token)
            else:
                store = MemoryDataLayer()
                print("store: memory (FINAGENT_AGENTS_DATA_URL unset)", file=sys.stderr)
        hub = EventHub(settings.event_retention)
        runner = Runner(
            workflows,
            store,
            make_llm=make_llm,
            max_runs=settings.max_runs,
            requests_per_second=settings.requests_per_second,
            events=hub,
        )
        app.state.runner, app.state.events = runner, hub
        if settings.api_token is None and settings.api_host not in LOOPBACK:
            log.warning(
                "FINAGENT_AGENTS_API_TOKEN is unset and the API listens on %s: anyone who can "
                "reach the port can start paid runs",
                settings.api_host,
            )
        try:
            if n := await mark_interrupted(store):
                log.warning("marked %d interrupted run(s) failed", n)
        except httpx.HTTPError as e:
            log.warning("could not check for interrupted runs: %s", e)
        try:
            yield
        finally:
            await runner.shutdown()
            if owned is not None:
                await owned.aclose()

    app = FastAPI(
        title="FinAgent Agents",
        version="1",
        lifespan=lifespan,
        generate_unique_id_function=lambda route: route.name,
        openapi_url=None if settings.api_token else "/openapi.json",  # docs only when open
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.api_allowed_hosts)

    @app.middleware("http")
    async def same_site_only(request: Request, call_next):
        if request.headers.get("sec-fetch-site") in CROSS_SITE:
            return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
        return await call_next(request)

    def auth(authorization: str | None = Header(default=None)) -> None:
        if settings.api_token is None:
            return
        expected = f"Bearer {settings.api_token}"
        if authorization is None or not secrets.compare_digest(authorization, expected):
            raise HTTPException(401, "invalid or missing bearer token")

    v1 = "/v1"
    deps = [Depends(auth)]

    @app.get(f"{v1}/health", dependencies=deps)
    def health() -> dict:
        return {"status": "ok", "active_runs": len(app.state.runner.active)}

    @app.get(f"{v1}/workflows", dependencies=deps)
    def list_workflows() -> list[WorkflowInfo]:
        return [_info(wf) for wf in workflows.values()]

    @app.post(f"{v1}/workflows/{{name}}/runs", status_code=202, dependencies=deps)
    async def start_run(name: str, body: StartRun) -> RunStarted:
        """Start a run in the background. Follow it at /runs/{run_id}/events."""
        try:
            run = await app.state.runner.start(name, body.inputs)
        except WorkflowError as e:
            raise HTTPException(404, str(e)) from None
        except InputError as e:
            raise HTTPException(422, str(e)) from None
        except httpx.HTTPError as e:  # the run could not be recorded, so it never started
            raise HTTPException(503, f"data API unavailable: {e}") from None
        return RunStarted(
            run_id=run.run_id, workflow=run.workflow, status=run.status, started_at=run.started_at
        )

    @app.get(f"{v1}/runs/{{run_id}}/events", dependencies=deps)
    async def run_events(
        run_id: str, last_event_id: int = Header(default=0, alias="Last-Event-ID")
    ) -> StreamingResponse:
        """Server-sent events, replayed from the start (or after Last-Event-ID), ending with
        `done`. 404 once the run is no longer held in memory: read it from the data API."""
        hub: EventHub = app.state.events
        if hub.get(run_id) is None:
            raise HTTPException(404, f"no live events for run {run_id!r}")

        async def stream() -> AsyncIterator[str]:
            async for event in hub.subscribe(run_id, after=last_event_id, keepalive=keepalive):
                yield _sse(event)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post(f"{v1}/runs/{{run_id}}/cancel", status_code=202, dependencies=deps)
    def cancel_run(run_id: str) -> dict:
        if not app.state.runner.cancel(run_id):
            raise HTTPException(404, f"run {run_id!r} is not running here")
        return {"run_id": run_id, "status": "cancelling"}

    return app
