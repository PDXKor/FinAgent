import time
from pathlib import Path

import duckdb
import pandas as pd

SCHEMA = Path(__file__).with_name("schema.sql")
VIEWS = Path(__file__).with_name("views.sql")

# DuckDB's wording for "another process has the file open": Windows / POSIX.
LOCK_MARKERS = ("being used by another process", "Could not set lock")
LOCK_RETRY_SECONDS = 5


class DatabaseLockedError(Exception):
    pass


def connect(path: str | Path, wait: float = 0, sleep=time.sleep) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the DuckDB file and ensure the schema exists.

    DuckDB allows one process at a time. If another process holds the file, retry for up to
    `wait` seconds, then raise DatabaseLockedError.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    waited = 0.0
    while True:
        try:
            con = duckdb.connect(str(path))
            break
        except duckdb.IOException as e:
            if not any(marker in str(e) for marker in LOCK_MARKERS):
                raise
            if waited + LOCK_RETRY_SECONDS > wait:
                raise DatabaseLockedError(
                    f"database is in use by another process: {path} (close any DuckDB shell or UI)"
                ) from e
            sleep(LOCK_RETRY_SECONDS)
            waited += LOCK_RETRY_SECONDS
    con.execute(SCHEMA.read_text())
    con.execute(VIEWS.read_text())
    return con


def upsert(con: duckdb.DuckDBPyConnection, table: str, rows: list[dict], keys: list[str]) -> int:
    """Insert rows, updating only the supplied non-key columns on key conflict.

    Duplicate keys within a batch are collapsed, last wins. Returns rows written.
    """
    if not rows:
        return 0
    df = pd.DataFrame(rows, dtype=object).drop_duplicates(subset=keys, keep="last")
    cols = list(df.columns)
    updates = [c for c in cols if c not in keys]
    action = (
        "DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in updates)
        if updates
        else "DO NOTHING"
    )
    con.register("_rows", df)
    try:
        con.execute(
            f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _rows "
            f"ON CONFLICT ({', '.join(keys)}) {action}"
        )
    finally:
        con.unregister("_rows")
    return len(df)
