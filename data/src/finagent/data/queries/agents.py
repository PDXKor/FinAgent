import json
import sqlite3
from datetime import UTC, datetime

from finagent.data.db import upsert
from finagent.data.queries import rows

COLUMNS = (
    "run_id", "workflow", "status", "inputs", "output", "error", "bindings",
    "started_at", "finished_at", "input_tokens", "output_tokens", "cache_read_tokens",
)  # fmt: skip
JSON_COLUMNS = ("inputs", "output", "bindings")


def _naive_utc(v):
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone(UTC).replace(tzinfo=None)
    return v


def save_agent_run(con: sqlite3.Connection, run: dict) -> None:
    """Insert or replace by run_id. JSON fields take any JSON-serializable value."""
    unknown = set(run) - set(COLUMNS)
    if unknown:
        raise ValueError(f"unknown agent_runs columns: {sorted(unknown)}")
    row = {k: json.dumps(v) if k in JSON_COLUMNS else _naive_utc(v) for k, v in run.items()}
    upsert(con, "agent_runs", [row], ["run_id"])


def get_agent_run(con: sqlite3.Connection, run_id: str) -> dict | None:
    found = rows(con.execute("SELECT * FROM agent_runs WHERE run_id = ?", [run_id]))
    if not found:
        return None
    run = found[0]
    for k in JSON_COLUMNS:
        run[k] = json.loads(run[k]) if run[k] is not None else None
    return run
