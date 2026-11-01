import httpx

from recon.config import Settings
from recon.jobs import REGISTRY
from recon.runner import Runner, RunResult
from recon.store.db import DatabaseLockedError, connect
from recon.watchlist import WatchlistError


def _execute(
    settings: Settings, label: str, client: httpx.Client | None, action, lock_wait: float = 0
) -> int:
    """Open the DB, run `action(runner)`, print a one-line result. Returns an exit code."""
    try:
        con = connect(settings.db_path, wait=lock_wait)
    except DatabaseLockedError as e:
        if client is not None:
            client.close()
        print(f"{label}: failed: {e}", flush=True)
        return 1
    try:
        res: RunResult = action(Runner(con, client, settings.raw_dir))
    except WatchlistError as e:
        print(f"{label}: failed: {e}", flush=True)
        return 1
    finally:
        con.close()
        if client is not None:
            client.close()
    print(
        f"{label}: {res.status} requests={res.requests} rows={res.rows_written} errors={res.errors}",
        flush=True,
    )
    return 0 if res.status == "ok" else 1


def run_job(
    settings: Settings,
    job_name: str,
    client: httpx.Client | None = None,
    lock_wait: float = 0,
) -> int:
    client = client or httpx.Client(
        headers={"User-Agent": settings.sec_user_agent}, timeout=30, follow_redirects=True
    )
    job = REGISTRY[job_name](settings)
    return _execute(settings, job_name, client, lambda runner: runner.run(job), lock_wait)


def reparse_job(settings: Settings, job_name: str) -> int:
    job = REGISTRY[job_name](settings)
    return _execute(settings, f"{job_name}:reparse", None, lambda runner: runner.reparse(job))
