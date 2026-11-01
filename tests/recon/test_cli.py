from pathlib import Path

import httpx
import pytest

from recon.cli import main
from recon.store.db import connect

pytestmark = pytest.mark.component

BODY = (Path(__file__).parent / "fixtures" / "company_tickers_exchange.json").read_bytes()


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("FINAGENT_SEC_USER_AGENT", "FinAgent me@corp.com")
    monkeypatch.setenv("FINAGENT_DB_PATH", str(tmp_path / "t.duckdb"))
    monkeypatch.setenv("FINAGENT_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.chdir(tmp_path)  # keep a stray .env out of the way


def fake_client(seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, content=BODY)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_run_loads_companies_and_returns_zero(tmp_path):
    assert main(["run", "sec_tickers"], client=fake_client()) == 0
    con = connect(tmp_path / "t.duckdb")
    assert con.execute("SELECT count(*) FROM companies").fetchone()[0] == 4
    assert con.execute("SELECT count(*) FROM tickers").fetchone()[0] == 5
    con.close()


def test_run_returns_nonzero_when_run_fails():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert main(["run", "sec_tickers"], client=client) == 1


def test_run_sends_configured_user_agent_by_default(monkeypatch):
    seen = []
    real = httpx.Client

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=BODY)

    def patched(**kw):
        return real(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr("recon.cli.httpx.Client", patched)
    assert main(["run", "sec_tickers"]) == 0
    assert seen[0].headers["user-agent"] == "FinAgent me@corp.com"


def test_unknown_job_is_rejected():
    with pytest.raises(SystemExit):
        main(["run", "nope"])


def test_status_shows_last_run_and_row_counts(capsys):
    main(["run", "sec_tickers"], client=fake_client())
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "sec_tickers" in out and "ok" in out
    assert "companies" in out and "4" in out
    assert ":<" not in out  # malformed format spec leaks literally


def test_status_on_empty_db_does_not_crash(capsys):
    assert main(["status"]) == 0
    assert "no runs" in capsys.readouterr().out.lower()


FIXTURES = Path(__file__).parent / "fixtures"
ROUTES = {
    "company_tickers_exchange.json": "company_tickers_exchange.json",
    "/submissions/CIK0000320193.json": "submissions_0000320193.json",
    "/companyfacts/CIK0000320193.json": "companyfacts_0000320193.json",
}


def router_client():
    def handler(request):
        for needle, fixture in ROUTES.items():
            if needle in str(request.url):
                return httpx.Response(200, content=(FIXTURES / fixture).read_bytes())
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def watchlist(monkeypatch, tmp_path):
    path = tmp_path / "slice.txt"
    path.write_text("AAPL\n")
    monkeypatch.setenv("FINAGENT_SLICE_FILE", str(path))


def counts(tmp_path):
    con = connect(tmp_path / "t.duckdb")
    out = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("filings", "facts")}
    out["sic"] = con.execute("SELECT sic FROM companies WHERE cik = '0000320193'").fetchone()[0]
    con.close()
    return out


def test_full_pipeline_populates_filings_and_facts(watchlist, tmp_path):
    for job in ("sec_tickers", "sec_submissions", "sec_companyfacts"):
        assert main(["run", job], client=router_client()) == 0
    assert counts(tmp_path) == {"filings": 3, "facts": 5, "sic": "3571"}


def test_pipeline_rerun_creates_no_duplicates(watchlist, tmp_path):
    for _ in range(2):
        for job in ("sec_tickers", "sec_submissions", "sec_companyfacts"):
            assert main(["run", job], client=router_client()) == 0
    assert counts(tmp_path) == {"filings": 3, "facts": 5, "sic": "3571"}


def test_missing_watchlist_fails_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("FINAGENT_SLICE_FILE", str(tmp_path / "nope.txt"))
    assert main(["run", "sec_submissions"], client=router_client()) == 1
    assert "nope.txt" in capsys.readouterr().out


def test_reparse_rebuilds_tables_from_raw_without_network(watchlist, tmp_path, monkeypatch):
    for job in ("sec_tickers", "sec_submissions"):
        assert main(["run", job], client=router_client()) == 0
    con = connect(tmp_path / "t.duckdb")
    con.execute("DELETE FROM filings")
    con.close()

    def no_network(**kw):
        raise AssertionError("reparse must not create an HTTP client")

    monkeypatch.setattr("recon.pipeline.httpx.Client", no_network)
    assert main(["reparse", "sec_submissions"]) == 0
    assert counts(tmp_path)["filings"] == 3


def test_reparse_unknown_job_is_rejected():
    with pytest.raises(SystemExit):
        main(["reparse", "nope"])


@pytest.fixture
def jobs_file(tmp_path):
    path = tmp_path / "jobs.yaml"
    path.write_text(
        "jobs:\n"
        '  sec_tickers: { schedule: "0 6 * * *" }\n'
        '  sec_submissions: { schedule: "0 7 * * 1-5" }\n'
    )
    return str(path)


def test_schedule_list_shows_jobs_cron_and_next_run(jobs_file, capsys):
    assert main(["schedule", "--list", "--file", jobs_file]) == 0
    out = capsys.readouterr().out
    assert "sec_tickers" in out and "0 6 * * *" in out
    assert "sec_submissions" in out and "0 7 * * 1-5" in out
    assert "UTC" in out


def test_schedule_starts_blocking_scheduler_with_all_jobs(jobs_file, monkeypatch):
    started = []
    monkeypatch.setattr(
        "apscheduler.schedulers.blocking.BlockingScheduler.start",
        lambda self: started.append(sorted(j.id for j in self.get_jobs())),
    )
    assert main(["schedule", "--file", jobs_file]) == 0
    assert started == [["sec_submissions", "sec_tickers"]]


def test_schedule_with_bad_file_fails_cleanly(tmp_path, capsys):
    assert main(["schedule", "--file", str(tmp_path / "missing.yaml")]) == 1
    assert "missing.yaml" in capsys.readouterr().out


def test_scheduled_run_executes_the_job(jobs_file, tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr("recon.cli.run_job", lambda settings, name, **kw: ran.append(name) or 0)
    monkeypatch.setattr(
        "apscheduler.schedulers.blocking.BlockingScheduler.start",
        lambda self: [j.func(*j.args) for j in self.get_jobs()],
    )
    assert main(["schedule", "--file", jobs_file]) == 0
    assert sorted(ran) == ["sec_submissions", "sec_tickers"]


def test_run_and_status_report_locked_database_cleanly(monkeypatch, capsys):
    from recon.store.db import DatabaseLockedError

    def locked(path, wait=0):
        raise DatabaseLockedError(f"database is in use by another process: {path}")

    monkeypatch.setattr("recon.pipeline.connect", locked)
    monkeypatch.setattr("recon.cli.connect", locked)
    assert main(["run", "sec_tickers"], client=fake_client()) == 1
    assert main(["status"]) == 1
    out = capsys.readouterr().out
    assert out.count("in use by another process") == 2


def test_status_keeps_columns_separated_for_long_job_names(capsys):
    main(["status"])  # create the DB
    con = connect(Path(__import__("os").environ["FINAGENT_DB_PATH"]))
    con.execute(
        "INSERT INTO ingest_runs (run_id, job, started_at, status, requests, rows_written, errors) "
        "VALUES ('r', 'sec_companyfacts:reparse', now(), 'ok', 1, 1, 0)"
    )
    con.close()
    capsys.readouterr()
    main(["status"])
    assert "sec_companyfacts:reparse " in capsys.readouterr().out


def frames_client():
    body = (FIXTURES / "frames_public_float.json").read_bytes()

    def handler(request):
        # Quarters that haven't filed yet are 404 on the real API.
        if "CY2026" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_sec_frames_loads_public_float_and_tolerates_missing_quarters(tmp_path, capsys):
    assert main(["run", "sec_frames"], client=frames_client()) == 0
    assert "sec_frames: ok" in capsys.readouterr().out
    con = connect(tmp_path / "t.duckdb")
    assert con.execute("SELECT count(*) FROM public_float").fetchone()[0] == 3
    con.close()


def test_small_cap_candidates_end_to_end(tmp_path):
    # Tesla (CIK 1318605) gets a $1.5B float, Apple (320193) a $3T float; both are in the tickers fixture.
    body = (
        b'{"data":['
        b'{"accn":"a1","cik":1318605,"loc":"US-TX","end":"2025-06-30","val":1500000000},'
        b'{"accn":"a2","cik":320193,"loc":"US-CA","end":"2025-03-28","val":3000000000000}]}'
    )
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    )
    assert main(["run", "sec_tickers"], client=router_client()) == 0
    assert main(["run", "sec_frames"], client=client) == 0
    con = connect(tmp_path / "t.duckdb")
    got = con.execute(
        "SELECT ticker, exchange, public_float FROM v_small_cap_candidates"
    ).fetchall()
    con.close()
    assert got == [("TSLA", "Nasdaq", 1_500_000_000)]
