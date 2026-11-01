import sqlite3
import time
from datetime import date, datetime

import pytest

from finagent.data import db
from finagent.data.db import DatabaseLockedError, connect, is_locked, upsert

pytestmark = pytest.mark.component

TABLES = {"companies", "tickers", "filings", "facts", "public_float", "ingest_runs", "source_state"}
VIEWS = {"v_recent_filings", "v_latest_financials", "v_small_cap_candidates"}


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


def names(con, kind):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = ?", [kind])}


def test_connect_creates_schema(con):
    assert TABLES <= names(con, "table")
    assert VIEWS <= names(con, "view")


def test_connect_uses_wal(con):
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_connect_creates_parent_dir(tmp_path):
    c = connect(tmp_path / "nested" / "dir" / "t.db")
    c.close()
    assert (tmp_path / "nested" / "dir" / "t.db").exists()


def test_connect_is_idempotent(tmp_path):
    connect(tmp_path / "t.db").close()
    c = connect(tmp_path / "t.db")
    assert c.execute("SELECT count(*) FROM companies").fetchone()[0] == 0
    c.close()


def test_connect_skips_schema_when_unchanged(tmp_path):
    connect(tmp_path / "t.db").close()
    holder = connect(tmp_path / "t.db")
    holder.execute("BEGIN IMMEDIATE")  # an open write transaction must not block a second connect
    try:
        connect(tmp_path / "t.db").close()
    finally:
        holder.rollback()
        holder.close()


def test_connect_reapplies_views_when_script_changes(tmp_path, monkeypatch):
    connect(tmp_path / "t.db").close()
    views = tmp_path / "views.sql"
    views.write_text("DROP VIEW IF EXISTS v_extra; CREATE VIEW v_extra AS SELECT 1 AS one;")
    monkeypatch.setattr(db, "VIEWS", views)
    c = connect(tmp_path / "t.db")
    assert "v_extra" in names(c, "view")
    c.close()


def test_upsert_inserts_rows(con):
    n = upsert(con, "companies", [{"cik": "0000320193", "name": "Apple Inc."}], ["cik"])
    assert n == 1
    assert con.execute("SELECT name FROM companies").fetchone() == ("Apple Inc.",)


def test_upsert_updates_only_given_columns(con):
    upsert(con, "companies", [{"cik": "1", "name": "Old", "sic": "7372"}], ["cik"])
    upsert(con, "companies", [{"cik": "1", "name": "New"}], ["cik"])
    assert con.execute("SELECT name, sic FROM companies").fetchall() == [("New", "7372")]


def test_upsert_dedupes_keys_within_batch_last_wins(con):
    upsert(con, "companies", [{"cik": "1", "name": "A"}, {"cik": "1", "name": "B"}], ["cik"])
    assert con.execute("SELECT name FROM companies").fetchall() == [("B",)]


def test_upsert_empty_is_noop(con):
    assert upsert(con, "companies", [], ["cik"]) == 0


def test_upsert_fills_missing_columns_with_null(con):
    upsert(con, "companies", [{"cik": "1", "name": "A", "sic": "7372"}, {"cik": "2"}], ["cik"])
    assert con.execute("SELECT cik, name, sic FROM companies ORDER BY cik").fetchall() == [
        ("1", "A", "7372"),
        ("2", None, None),
    ]


def test_upsert_with_only_key_columns_ignores_conflicts(con):
    upsert(con, "tickers", [{"ticker": "AAPL", "cik": "1"}], ["ticker"])
    assert upsert(con, "tickers", [{"ticker": "AAPL"}], ["ticker"]) == 1
    assert con.execute("SELECT cik FROM tickers").fetchone() == ("1",)


def test_upsert_stores_dates_and_timestamps_as_iso_text(con):
    upsert(
        con,
        "filings",
        [
            {
                "accession_no": "a",
                "filed_date": date(2024, 11, 1),
                "ingested_at": datetime(2024, 11, 2, 3, 4, 5),
            }
        ],
        ["accession_no"],
    )
    assert con.execute("SELECT filed_date, ingested_at FROM filings").fetchone() == (
        "2024-11-01",
        "2024-11-02 03:04:05",
    )


def test_upsert_rolls_back_the_whole_batch_on_error(con):
    with pytest.raises(sqlite3.OperationalError):
        upsert(con, "companies", [{"cik": "1"}, {"cik": "2", "nope": "x"}], ["cik"])
    assert con.execute("SELECT count(*) FROM companies").fetchone()[0] == 0
    assert not con.in_transaction


def test_upsert_joins_an_open_transaction(con):
    con.execute("BEGIN")
    upsert(con, "companies", [{"cik": "1"}], ["cik"])
    assert con.in_transaction  # the caller owns commit
    con.rollback()
    assert con.execute("SELECT count(*) FROM companies").fetchone()[0] == 0


def test_writes_are_visible_to_other_connections_immediately(tmp_path):
    a = connect(tmp_path / "t.db")
    b = connect(tmp_path / "t.db")
    upsert(a, "companies", [{"cik": "1", "name": "A"}], ["cik"])
    assert b.execute("SELECT name FROM companies").fetchone() == ("A",)
    a.close()
    b.close()


def test_readers_do_not_block_while_a_writer_holds_the_lock(tmp_path):
    writer = connect(tmp_path / "t.db")
    upsert(writer, "companies", [{"cik": "1", "name": "A"}], ["cik"])
    writer.execute("BEGIN IMMEDIATE")
    upsert(writer, "companies", [{"cik": "2", "name": "B"}], ["cik"])
    reader = connect(tmp_path / "t.db")
    try:
        # Sees the last committed state; the writer's open transaction is invisible.
        assert reader.execute("SELECT count(*) FROM companies").fetchone()[0] == 1
    finally:
        reader.close()
        writer.rollback()
        writer.close()


def test_second_writer_gets_a_lock_error_that_is_locked_detects(tmp_path):
    first = connect(tmp_path / "locked.db")
    first.execute("BEGIN IMMEDIATE")
    second = connect(tmp_path / "locked.db")
    try:
        with pytest.raises(sqlite3.OperationalError) as exc:
            second.execute("BEGIN IMMEDIATE")
        assert is_locked(exc.value)
    finally:
        second.close()
        first.rollback()
        first.close()


def test_second_writer_waits_for_the_lock_within_the_wait_budget(tmp_path):
    first = connect(tmp_path / "locked.db")
    first.execute("BEGIN IMMEDIATE")
    second = connect(tmp_path / "locked.db", wait=0.3)
    start = time.monotonic()
    try:
        with pytest.raises(sqlite3.OperationalError):
            second.execute("BEGIN IMMEDIATE")
        assert time.monotonic() - start >= 0.25
    finally:
        second.close()
        first.rollback()
        first.close()


def test_connect_raises_locked_error_when_schema_cannot_be_written(tmp_path, monkeypatch):
    connect(tmp_path / "locked.db").close()
    holder = connect(tmp_path / "locked.db")
    holder.execute("BEGIN IMMEDIATE")
    # Force a schema change so the connecting side has to write.
    views = tmp_path / "views.sql"
    views.write_text("DROP VIEW IF EXISTS v_extra; CREATE VIEW v_extra AS SELECT 1 AS one;")
    monkeypatch.setattr(db, "VIEWS", views)
    try:
        with pytest.raises(DatabaseLockedError, match="locked.db"):
            connect(tmp_path / "locked.db")
    finally:
        holder.rollback()
        holder.close()


def test_connect_does_not_mask_other_operational_errors(tmp_path):
    bad = tmp_path / "not_a_db.db"
    bad.write_bytes(b"this is not a sqlite file" * 100)
    with pytest.raises(sqlite3.DatabaseError) as exc:
        connect(bad)
    assert not isinstance(exc.value, DatabaseLockedError)
