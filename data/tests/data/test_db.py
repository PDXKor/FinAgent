import pytest

from finagent.data.db import connect, upsert

pytestmark = pytest.mark.component

TABLES = {"companies", "tickers", "filings", "facts", "ingest_runs", "source_state"}


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    yield c
    c.close()


def test_connect_creates_schema(con):
    names = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert TABLES <= names


def test_connect_creates_parent_dir(tmp_path):
    c = connect(tmp_path / "nested" / "dir" / "t.duckdb")
    c.close()
    assert (tmp_path / "nested" / "dir" / "t.duckdb").exists()


def test_connect_is_idempotent(tmp_path):
    connect(tmp_path / "t.duckdb").close()
    c = connect(tmp_path / "t.duckdb")
    assert c.execute("SELECT count(*) FROM companies").fetchone()[0] == 0
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


def test_connect_raises_clear_error_when_another_process_holds_the_file(tmp_path):
    import subprocess
    import sys

    from finagent.data.db import DatabaseLockedError

    path = tmp_path / "locked.duckdb"
    script = (
        "import duckdb, time; "
        f"c = duckdb.connect({str(path)!r}); print('ready', flush=True); time.sleep(60)"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ready"
        with pytest.raises(DatabaseLockedError, match="locked.duckdb"):
            connect(path)
    finally:
        holder.kill()
        holder.wait()


def test_connect_retries_while_locked_then_succeeds(tmp_path, monkeypatch):
    import duckdb

    from finagent.data import db

    real = duckdb.connect
    attempts = []

    def flaky(path):
        attempts.append(path)
        if len(attempts) < 3:
            raise duckdb.IOException(
                "Cannot open file: The process cannot access the file because it is being used by another process."
            )
        return real(path)

    sleeps = []
    monkeypatch.setattr(db.duckdb, "connect", flaky)
    c = connect(tmp_path / "t.duckdb", wait=60, sleep=sleeps.append)
    c.close()
    assert len(attempts) == 3
    assert sleeps == [5, 5]


def test_connect_gives_up_after_wait_budget(tmp_path, monkeypatch):
    import duckdb

    from finagent.data import db
    from finagent.data.db import DatabaseLockedError

    def always_locked(path):
        raise duckdb.IOException("Could not set lock on file")

    monkeypatch.setattr(db.duckdb, "connect", always_locked)
    sleeps = []
    with pytest.raises(DatabaseLockedError):
        connect(tmp_path / "t.duckdb", wait=12, sleep=sleeps.append)
    assert sum(sleeps) <= 12 and len(sleeps) >= 2


def test_connect_does_not_mask_other_io_errors(tmp_path, monkeypatch):
    import duckdb

    from finagent.data import db
    from finagent.data.db import DatabaseLockedError

    def corrupt(path):
        raise duckdb.IOException("database file version number 69 is too new")

    monkeypatch.setattr(db.duckdb, "connect", corrupt)
    with pytest.raises(duckdb.IOException) as exc:
        connect(tmp_path / "t.duckdb", wait=10, sleep=lambda s: None)
    assert not isinstance(exc.value, DatabaseLockedError)
