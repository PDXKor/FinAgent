"""Read-only browsing of any table or view: filters, sorting, paging.

Table and column names come from the request, so they are checked against the live schema
before use; filter values are always bound parameters.
"""

import sqlite3

from finagent.data.queries import rows

# Filter operator -> SQL after the column. LIKE is case-insensitive for ASCII.
OPS = {
    "eq": "= ?",
    "ne": "!= ?",
    "lt": "< ?",
    "lte": "<= ?",
    "gt": "> ?",
    "gte": ">= ?",
    "contains": "LIKE ? ESCAPE '\\'",
    "starts": "LIKE ? ESCAPE '\\'",
    "null": "IS NULL",
    "notnull": "IS NOT NULL",
}
NO_VALUE = {"null", "notnull"}


class BrowseError(ValueError):
    pass


def list_tables(con: sqlite3.Connection) -> list[dict]:
    """Tables then views, by name, each with its columns."""
    found = con.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') "
        "AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    return [{"name": n, "kind": t, "columns": _columns(con, n)} for n, t in found]


def _columns(con: sqlite3.Connection, table: str) -> list[dict]:
    info = con.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [{"name": c[1], "type": c[2] or None} for c in info]


def _value(raw: str) -> int | float | str:
    """Numbers compare as numbers (view columns may have no type affinity)."""
    for cast in (int, float):
        try:
            return cast(raw)
        except ValueError:
            pass
    return raw


def _like(raw: str, prefix_only: bool) -> str:
    escaped = raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%" if prefix_only else f"%{escaped}%"


def browse(
    con: sqlite3.Connection,
    table: str,
    filters: list[tuple[str, str, str]] = (),
    sort: str | None = None,
    order: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """One page of `table`. `filters` are (column, op, value), ANDed. Returns columns, rows,
    and the filtered total. KeyError if the table does not exist; BrowseError if a column,
    operator or order is invalid."""
    known = {t["name"]: t for t in list_tables(con)}
    if table not in known:
        raise KeyError(table)
    columns = known[table]["columns"]
    names = {c["name"] for c in columns}

    where, params = [], []
    for col, op, raw in filters:
        if col not in names:
            raise BrowseError(f"unknown column {col!r}")
        if op not in OPS:
            raise BrowseError(f"unknown operator {op!r}; use one of {sorted(OPS)}")
        where.append(f'"{col}" {OPS[op]}')
        if op in ("contains", "starts"):
            params.append(_like(raw, op == "starts"))
        elif op not in NO_VALUE:
            params.append(_value(raw))
    clause = f" WHERE {' AND '.join(where)}" if where else ""

    if sort is not None and sort not in names:
        raise BrowseError(f"unknown sort column {sort!r}")
    if order not in ("asc", "desc"):
        raise BrowseError(f"order must be asc or desc, not {order!r}")
    order_by = f' ORDER BY "{sort}" {order.upper()} NULLS LAST' if sort else ""

    total = con.execute(f'SELECT count(*) FROM "{table}"{clause}', params).fetchone()[0]
    page = rows(
        con.execute(
            f'SELECT * FROM "{table}"{clause}{order_by} LIMIT ? OFFSET ?', [*params, limit, offset]
        )
    )
    return {"table": table, "columns": columns, "rows": page, "total": total}
