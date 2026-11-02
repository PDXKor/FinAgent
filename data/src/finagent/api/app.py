import logging
import secrets
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from finagent.api.config import ApiSettings
from finagent.api.jobs import JobBusyError, JobManager
from finagent.api.schemas import (
    AgentRun,
    AgentRunIn,
    AgentRunPage,
    AnnualFinancials,
    Company,
    IngestRun,
    Job,
    JobStarted,
    TableInfo,
    TableRows,
)
from finagent.data.db import DatabaseLockedError, connect, is_locked
from finagent.data.queries.agents import get_agent_run, list_agent_runs, save_agent_run
from finagent.data.queries.browse import OPS, BrowseError, browse, list_tables
from finagent.data.queries.fundamentals import get_financials
from finagent.data.queries.ops import (
    latest_ingest_runs,
    list_ingest_runs,
    mark_ingest_interrupted,
    table_counts,
)
from finagent.data.queries.reference import get_company
from finagent.data.timeutil import utcnow
from finagent.recon.jobs import REGISTRY
from finagent.recon.scheduler import DEFAULT_FILE, ScheduleError, load_schedule

log = logging.getLogger(__name__)

MAX_FINANCIAL_ROWS = 20
MAX_INGEST_ROWS = 200
MAX_AGENT_RUN_ROWS = 200
MAX_BROWSE_ROWS = 500
FILTER_HELP = "column:op:value, repeatable. ops: " + ", ".join(sorted(OPS))
RETRY_AFTER_S = "1"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
# Browsers label requests from other sites; the proxies add tokens, so refuse those outright.
CROSS_SITE = {"cross-site", "same-site"}
RUN_STATUS = Literal["queued", "running", "ok", "failed", "timeout", "cancelled"]


def _naive_utc(t: datetime | None) -> datetime | None:
    """Request times may carry an offset; the store holds naive UTC."""
    if t is None or t.tzinfo is None:
        return t
    return t.astimezone(UTC).replace(tzinfo=None)


def _cursor(started_at: datetime, run_id: str) -> str:
    return f"{started_at.isoformat()}|{run_id}"


def _parse_cursor(cursor: str) -> tuple[datetime, str]:
    started, sep, run_id = cursor.rpartition("|")
    try:
        if not sep:
            raise ValueError
        return datetime.fromisoformat(started), run_id
    except ValueError:
        raise HTTPException(422, f"bad cursor {cursor!r}") from None


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
    jobs = JobManager(run_job or _recon_runner(settings))

    def db() -> closing[sqlite3.Connection]:
        return closing(connect(settings.db_path, wait=settings.api_lock_wait))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.api_token is None and settings.api_host not in LOOPBACK:
            log.warning(
                "FINAGENT_API_TOKEN is unset and the API listens on %s: anyone who can reach "
                "the port can use it",
                settings.api_host,
            )
        yield
        # Job threads die with the process; don't leave this process's run marked running.
        if (active := jobs.active) is not None:
            with db() as con:
                mark_ingest_interrupted(
                    con, active.job, active.started_at, utcnow(), "interrupted: API stopped"
                )

    app = FastAPI(
        title="FinAgentData",
        version="1",
        lifespan=lifespan,
        generate_unique_id_function=lambda route: route.name,  # clean generated client names
        openapi_url=None if settings.api_token else "/openapi.json",  # docs only when open
    )
    app.state.jobs = jobs
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

    @app.exception_handler(DatabaseLockedError)
    @app.exception_handler(sqlite3.OperationalError)
    async def _locked(request: Request, e: Exception) -> JSONResponse:
        if isinstance(e, DatabaseLockedError) or is_locked(e):
            return JSONResponse(
                {"detail": "database busy"}, status_code=503, headers={"Retry-After": RETRY_AFTER_S}
            )
        log.error("database error on %s %s", request.method, request.url.path, exc_info=e)
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

    @app.get(f"{v1}/agent-runs", dependencies=deps)
    def agent_runs(
        workflow: str | None = None,
        status: RUN_STATUS | None = None,
        cursor: str | None = None,
        limit: int = Query(50, ge=1, le=MAX_AGENT_RUN_ROWS),
    ) -> AgentRunPage:
        """Newest first. Page with `cursor` = the previous page's `next`."""
        after = _parse_cursor(cursor) if cursor else None
        with db() as con:
            found = list_agent_runs(con, workflow, status, after, limit)
        items = [AgentRun(**r) for r in found]
        last = items[-1] if len(items) == limit else None
        return AgentRunPage(
            items=items, next=_cursor(last.started_at, last.run_id) if last else None
        )

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
        job: str | None = None,
        status: Literal["running", "ok", "partial", "failed"] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        sort: Literal[
            "started_at", "job", "status", "requests", "rows_written", "errors", "duration"
        ] = "started_at",
        order: Literal["asc", "desc"] = "desc",
        limit: int = Query(50, ge=1, le=MAX_INGEST_ROWS),
    ) -> list[IngestRun]:
        """Filter by job, status, start time (`since` inclusive, `until` exclusive); sort by any
        column or `duration`."""
        bounds = [_naive_utc(t) for t in (since, until)]
        with db() as con:
            found = list_ingest_runs(con, job, limit, status, *bounds, sort=sort, order=order)
        return [IngestRun(**r) for r in found]

    @app.get(f"{v1}/tables", dependencies=deps)
    def tables() -> list[TableInfo]:
        """Every table and view with its columns, for the data viewer."""
        with db() as con:
            return [TableInfo(**t) for t in list_tables(con)]

    @app.get(f"{v1}/tables/{{name}}/rows", dependencies=deps)
    def table_rows(
        name: str,
        filter: Annotated[list[str] | None, Query(description=FILTER_HELP)] = None,
        sort: str | None = None,
        order: Literal["asc", "desc"] = "asc",
        limit: int = Query(50, ge=1, le=MAX_BROWSE_ROWS),
        offset: int = Query(0, ge=0),
    ) -> TableRows:
        """One page of a table or view. Filters are ANDed; `null`/`notnull` ignore the value."""
        parsed = []
        for f in filter or []:
            col, sep, rest = f.partition(":")
            op, _, value = rest.partition(":")
            if not sep or not op:
                raise HTTPException(422, f"filter {f!r} must be column:op:value")
            parsed.append((col, op, value))
        try:
            with db() as con:
                page = browse(con, name, parsed, sort, order, limit, offset)
        except KeyError:
            raise HTTPException(404, f"unknown table {name!r}") from None
        except BrowseError as e:
            raise HTTPException(422, str(e)) from None
        return TableRows(**page, limit=limit, offset=offset)

    @app.get(f"{v1}/ops/counts", dependencies=deps)
    def counts() -> dict[str, int]:
        """Row counts of the main tables."""
        with db() as con:
            return table_counts(con)

    return app
