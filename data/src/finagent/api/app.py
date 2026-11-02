import secrets
import sqlite3
from collections.abc import Callable
from contextlib import closing

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from finagent.api.config import ApiSettings
from finagent.api.jobs import JobBusyError, JobManager
from finagent.api.schemas import (
    AgentRun,
    AgentRunIn,
    AnnualFinancials,
    Company,
    IngestRun,
    Job,
    JobStarted,
)
from finagent.data.db import DatabaseLockedError, connect, is_locked
from finagent.data.queries.agents import get_agent_run, save_agent_run
from finagent.data.queries.fundamentals import get_financials
from finagent.data.queries.ops import latest_ingest_runs, list_ingest_runs, table_counts
from finagent.data.queries.reference import get_company
from finagent.recon.jobs import REGISTRY
from finagent.recon.scheduler import DEFAULT_FILE, ScheduleError, load_schedule

MAX_FINANCIAL_ROWS = 20
MAX_INGEST_ROWS = 200
RETRY_AFTER_S = "1"


def _recon_runner(settings: ApiSettings) -> Callable[[str], object]:
    """Default job runner: real recon ingestion against the API's database."""

    def run(job: str) -> object:
        from finagent.recon.config import Settings
        from finagent.recon.pipeline import ingest

        # Built per run: needs FINAGENT_SEC_USER_AGENT, which read-only use of the API doesn't.
        recon = Settings(db_path=settings.db_path)
        return ingest(recon, job, lock_wait=settings.job_lock_wait)

    return run


def create_app(
    settings: ApiSettings | None = None, run_job: Callable[[str], object] | None = None
) -> FastAPI:
    """Handlers are sync (FastAPI threadpool). Each opens its own connection: sqlite3
    connections must stay on the thread that made them. `run_job(name)` runs one recon job
    (blocking); tests pass a fake."""
    settings = settings or ApiSettings()
    app = FastAPI(
        title="FinAgentData",
        version="1",
        generate_unique_id_function=lambda route: route.name,  # clean generated client names
    )
    jobs = app.state.jobs = JobManager(run_job or _recon_runner(settings))

    def db() -> closing[sqlite3.Connection]:
        return closing(connect(settings.db_path, wait=settings.api_lock_wait))

    def auth(authorization: str | None = Header(default=None)) -> None:
        if settings.api_token is None:
            return
        expected = f"Bearer {settings.api_token}"
        if authorization is None or not secrets.compare_digest(authorization, expected):
            raise HTTPException(401, "invalid or missing bearer token")

    @app.exception_handler(DatabaseLockedError)
    @app.exception_handler(sqlite3.OperationalError)
    async def _locked(request: Request, e: Exception) -> JSONResponse:
        if isinstance(e, DatabaseLockedError) or is_locked(e):
            return JSONResponse(
                {"detail": "database busy"}, status_code=503, headers={"Retry-After": RETRY_AFTER_S}
            )
        return JSONResponse({"detail": "database error"}, status_code=500)

    v1 = "/v1"
    deps = [Depends(auth)]

    @app.get(f"{v1}/health", dependencies=deps)
    def health() -> dict:
        with db() as con:
            con.execute("SELECT 1")
        return {"status": "ok"}

    @app.get(f"{v1}/companies/{{ticker}}", dependencies=deps)
    def company(ticker: str) -> Company:
        with db() as con:
            found = get_company(con, ticker)
        if found is None:
            raise HTTPException(404, f"unknown ticker {ticker!r}")
        return Company(**found)

    @app.get(f"{v1}/companies/{{ticker}}/financials", dependencies=deps)
    def financials(
        ticker: str, limit: int = Query(8, ge=1, le=MAX_FINANCIAL_ROWS)
    ) -> list[AnnualFinancials]:
        with db() as con:
            return [AnnualFinancials(**r) for r in get_financials(con, ticker, limit)]

    @app.put(f"{v1}/agent-runs/{{run_id}}", status_code=204, dependencies=deps)
    def put_agent_run(run_id: str, run: AgentRunIn) -> None:
        with db() as con:
            save_agent_run(con, {"run_id": run_id, **run.model_dump()})

    @app.get(f"{v1}/agent-runs/{{run_id}}", dependencies=deps)
    def agent_run(run_id: str) -> AgentRun:
        with db() as con:
            found = get_agent_run(con, run_id)
        if found is None:
            raise HTTPException(404, f"unknown run {run_id!r}")
        return AgentRun(**found)

    @app.get(f"{v1}/jobs", dependencies=deps)
    def list_jobs() -> list[Job]:
        """Recon jobs in dependency order, with their last run."""
        try:
            schedule = load_schedule(DEFAULT_FILE)
        except ScheduleError:
            schedule = {}
        with db() as con:
            last = {r["job"]: r for r in latest_ingest_runs(con)}
        active = jobs.active
        return [
            Job(
                name=name,
                schedule=schedule.get(name),
                running=active is not None and active.job == name,
                last_run=IngestRun(**last[name]) if name in last else None,
                last_error=jobs.last_error.get(name),
            )
            for name in REGISTRY
        ]

    @app.post(f"{v1}/jobs/{{name}}/runs", status_code=202, dependencies=deps)
    def start_job(name: str) -> JobStarted:
        """Start a job in the background. 409 if any job is running. Poll /jobs for progress."""
        if name not in REGISTRY:
            raise HTTPException(404, f"unknown job {name!r}")
        try:
            active = jobs.start(name)
        except JobBusyError as e:
            raise HTTPException(409, str(e)) from None
        return JobStarted(job=active.job, started_at=active.started_at)

    @app.get(f"{v1}/ingest-runs", dependencies=deps)
    def ingest_runs(
        job: str | None = None, limit: int = Query(50, ge=1, le=MAX_INGEST_ROWS)
    ) -> list[IngestRun]:
        with db() as con:
            return [IngestRun(**r) for r in list_ingest_runs(con, job, limit)]

    @app.get(f"{v1}/ops/counts", dependencies=deps)
    def counts() -> dict[str, int]:
        """Row counts of the main tables."""
        with db() as con:
            return table_counts(con)

    return app
