import sqlite3
import zlib
from datetime import date, datetime
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")
VIEWS = Path(__file__).with_name("views.sql")

# SQLite has no date types. Dates and timestamps are stored, and read back, as ISO-8601 text.
sqlite3.register_adapter(date, date.isoformat)
sqlite3.register_adapter(datetime, lambda d: d.isoformat(sep=" "))


class DatabaseLockedError(Exception):
    pass


def connect(path: str | Path, wait: float = 0) -> sqlite3.Connection:
    """Open (creating if needed) the SQLite file and ensure the schema exists.

    WAL mode: readers never block, and never block the writer. Writers are serialized; a second
    writer retries for up to `wait` seconds, then raises DatabaseLockedError. Autocommit: each
    statement commits on its own unless wrapped in an explicit transaction.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=wait, isolation_level=None)
    try:
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
        _ensure_schema(con)
    except BaseException as e:
        con.close()
        if is_locked(e):
            raise DatabaseLockedError(f"database is locked by another writer: {path}") from e
        raise
    return con


def is_locked(e: BaseException) -> bool:
    """True for SQLite's "another connection holds the write lock" errors."""
    return isinstance(e, sqlite3.OperationalError) and ("locked" in str(e) or "busy" in str(e))


def _ensure_schema(con: sqlite3.Connection) -> None:
    """Apply schema and views when their text changed. `user_version` holds a hash of both."""
    script = SCHEMA.read_text(encoding="utf-8") + "\n" + VIEWS.read_text(encoding="utf-8")
    version = zlib.crc32(script.encode()) & 0x7FFFFFFF
    if con.execute("PRAGMA user_version").fetchone()[0] == version:
        return
    try:
        con.executescript(f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
    except BaseException:
        if con.in_transaction:
            con.rollback()
        raise


def upsert(con: sqlite3.Connection, table: str, rows: list[dict], keys: list[str]) -> int:
    """Insert rows, updating only the supplied non-key columns on key conflict.

    Duplicate keys within a batch are collapsed, last wins. Returns rows written.
    """
    if not rows:
        return 0
    cols = list(dict.fromkeys(c for r in rows for c in r))
    batch = list({tuple(r.get(k) for k in keys): r for r in rows}.values())
    updates = [c for c in cols if c not in keys]
    action = (
        "DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in updates)
        if updates
        else "DO NOTHING"
    )
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT ({', '.join(keys)}) {action}"
    )
    params = [[r.get(c) for c in cols] for r in batch]
    own_tx = not con.in_transaction
    if own_tx:
        con.execute("BEGIN")
    try:
        con.executemany(sql, params)
    except BaseException:
        if own_tx:
            con.rollback()
        raise
    if own_tx:
        con.commit()
    return len(batch)
