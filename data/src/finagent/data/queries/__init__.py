"""Read/write API for consumers. One module per domain. Callers pass an open connection."""

import sqlite3


def rows(cur: sqlite3.Cursor) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
