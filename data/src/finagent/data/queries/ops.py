import sqlite3

from finagent.data.queries import rows

COUNTED_TABLES = ("companies", "tickers", "filings", "facts", "public_float")
RUN_COLUMNS = (
    "run_id, job, status, started_at, finished_at, requests, rows_written, errors, error_sample"
)


def latest_ingest_runs(con: sqlite3.Connection) -> list[dict]:
    """Most recent run per job, ordered by job."""
    return rows(
        con.execute(
            f"SELECT {RUN_COLUMNS} FROM ("
            "  SELECT *, row_number() OVER (PARTITION BY job ORDER BY started_at DESC) AS rn "
            "  FROM ingest_runs) WHERE rn = 1 ORDER BY job"
        )
    )


def list_ingest_runs(
    con: sqlite3.Connection, job: str | None = None, limit: int = 50
) -> list[dict]:
    """Recent runs, newest first, optionally for one job."""
    where, params = ("WHERE job = ?", [job]) if job else ("", [])
    return rows(
        con.execute(
            f"SELECT {RUN_COLUMNS} FROM ingest_runs {where} ORDER BY started_at DESC LIMIT ?",
            [*params, limit],
        )
    )


def table_counts(con: sqlite3.Connection, tables=COUNTED_TABLES) -> dict[str, int]:
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def mark_ingest_interrupted(con: sqlite3.Connection, job: str, since, now, reason: str) -> int:
    """Fail `job`'s runs still `running` that started at or after `since` (naive UTC)."""
    cur = con.execute(
        "UPDATE ingest_runs SET status = 'failed', finished_at = ?, error_sample = ? "
        "WHERE job = ? AND status = 'running' AND started_at >= ?",
        [now, reason, job, since],
    )
    return cur.rowcount
