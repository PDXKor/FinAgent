import sqlite3

import httpx

from finagent.data.db import DatabaseLockedError, connect, is_locked
from finagent.recon.config import Settings
from finagent.recon.jobs import REGISTRY
from finagent.recon.runner import Runner, RunResult
from finagent.recon.watchlist import WatchlistError


def _open_and_run(
    settings: Settings, client: httpx.Client | None, action, lock_wait: float = 0
) -> RunResult:
    """Open the DB, run `action(runner)`, close the DB and client. Raises on failure."""
    try:
        con = connect(settings.db_path, wait=lock_wait)
    except BaseException:
        if client is not None:
            client.close()
        raise
    try:
        return action(Runner(con, client, settings.raw_dir, raw_keep=settings.raw_keep))
    finally:
        con.close()
        if client is not None:
            client.close()


def _execute(
    settings: Settings, label: str, client: httpx.Client | None, action, lock_wait: float = 0
) -> int:
    """`_open_and_run`, printing a one-line result. Returns an exit code."""
    try:
        res = _open_and_run(settings, client, action, lock_wait)
    except (DatabaseLockedError, WatchlistError) as e:
        print(f"{label}: failed: {e}", flush=True)
        return 1
    except sqlite3.OperationalError as e:
        if not is_locked(e):
            raise
        print(
            f"{label}: failed: database is locked by another writer: {settings.db_path}", flush=True
        )
        return 1
    print(
        f"{label}: {res.status} requests={res.requests} rows={res.rows_written} errors={res.errors}",
        flush=True,
    )
    return 0 if res.status == "ok" else 1


def _sec_client(settings: Settings) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": settings.sec_user_agent}, timeout=30, follow_redirects=True
    )


def ingest(
    settings: Settings,
    job_name: str,
    client: httpx.Client | None = None,
    lock_wait: float = 0,
) -> RunResult:
    """Run one job; return its result. Raises if it cannot start or aborts (for callers like
    the API that report errors themselves)."""
    client = client or _sec_client(settings)
    job = REGISTRY[job_name](settings)
    return _open_and_run(settings, client, lambda runner: runner.run(job), lock_wait)


def run_job(
    settings: Settings,
    job_name: str,
    client: httpx.Client | None = None,
    lock_wait: float = 0,
) -> int:
    client = client or _sec_client(settings)
    job = REGISTRY[job_name](settings)
    return _execute(settings, job_name, client, lambda runner: runner.run(job), lock_wait)


def reparse_job(settings: Settings, job_name: str) -> int:
    job = REGISTRY[job_name](settings)
    return _execute(settings, f"{job_name}:reparse", None, lambda runner: runner.reparse(job))
