import threading

import pytest
from fastapi.testclient import TestClient

from finagent.api.app import create_app
from finagent.api.config import ApiSettings
from finagent.data.db import connect

pytestmark = pytest.mark.component

JOB_NAMES = ["sec_tickers", "sec_frames", "sec_submissions", "sec_companyfacts"]


class FakeRunner:
    """Blocks each job until released; records what ran."""

    def __init__(self, fail: Exception | None = None):
        self.release = threading.Event()
        self.started = threading.Event()
        self.ran: list[str] = []
        self.fail = fail

    def __call__(self, job: str) -> None:
        self.ran.append(job)
        self.started.set()
        self.release.wait(5)
        if self.fail:
            raise self.fail


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    con = connect(path)
    con.execute(
        "INSERT INTO ingest_runs (run_id, job, started_at, finished_at, status, requests, "
        "rows_written, errors) VALUES "
        "('a', 'sec_tickers', '2026-11-01 10:00:00', '2026-11-01 10:00:05', 'ok', 1, 10, 0), "
        "('b', 'sec_tickers', '2026-11-01 11:00:00', NULL, 'running', NULL, NULL, NULL), "
        "('c', 'sec_frames', '2026-11-01 09:00:00.250000', '2026-11-01 09:01:00', 'partial', 6, 5, 1)"
    )
    con.close()
    return path


def make(db_path, runner):
    app = create_app(ApiSettings(db_path=db_path, _env_file=None), run_job=runner)
    return app, TestClient(base_url="http://localhost", app=app)


def test_list_jobs_in_registry_order_with_last_run_and_schedule(db_path):
    _, c = make(db_path, FakeRunner())
    got = c.get("/v1/jobs").json()
    assert [j["name"] for j in got] == JOB_NAMES
    tickers, frames, subs = got[0], got[1], got[2]
    assert tickers["last_run"]["run_id"] == "b" and tickers["last_run"]["status"] == "running"
    assert tickers["schedule"] == "0 6 * * *"
    assert frames["last_run"]["status"] == "partial" and frames["last_run"]["errors"] == 1
    assert subs["last_run"] is None and subs["running"] is False


def test_timestamps_are_sent_as_utc(db_path):
    _, c = make(db_path, FakeRunner())
    run = c.get("/v1/ingest-runs?job=sec_frames").json()[0]
    assert run["started_at"] == "2026-11-01T09:00:00.250000Z"
    assert run["finished_at"] == "2026-11-01T09:01:00Z"


def test_start_job_runs_in_background_and_blocks_a_second_start(db_path):
    runner = FakeRunner()
    app, c = make(db_path, runner)
    got = c.post("/v1/jobs/sec_frames/runs")
    assert got.status_code == 202 and got.json()["job"] == "sec_frames"
    assert got.json()["started_at"].endswith("Z")
    assert runner.started.wait(5)
    jobs = {j["name"]: j for j in c.get("/v1/jobs").json()}
    assert jobs["sec_frames"]["running"] is True and jobs["sec_tickers"]["running"] is False

    busy = c.post("/v1/jobs/sec_tickers/runs")
    assert busy.status_code == 409 and "sec_frames" in busy.json()["detail"]

    runner.release.set()
    assert app.state.jobs.wait(5)
    assert c.get("/v1/jobs").json()[1]["running"] is False
    assert c.post("/v1/jobs/sec_tickers/runs").status_code == 202
    assert app.state.jobs.wait(5)
    assert runner.ran == ["sec_frames", "sec_tickers"]


def test_job_exception_is_reported_and_cleared_on_next_start(db_path):
    runner = FakeRunner(fail=RuntimeError("no user agent"))
    runner.release.set()
    app, c = make(db_path, runner)
    c.post("/v1/jobs/sec_tickers/runs")
    assert app.state.jobs.wait(5)
    tickers = c.get("/v1/jobs").json()[0]
    assert tickers["running"] is False
    assert tickers["last_error"] == "RuntimeError: no user agent"

    runner.fail = None
    c.post("/v1/jobs/sec_tickers/runs")
    assert app.state.jobs.wait(5)
    assert c.get("/v1/jobs").json()[0]["last_error"] is None


def test_unknown_job_is_404(db_path):
    _, c = make(db_path, FakeRunner())
    assert c.post("/v1/jobs/nope/runs").status_code == 404


def test_ingest_runs_newest_first_with_filter_and_limit_bounds(db_path):
    _, c = make(db_path, FakeRunner())
    assert [r["run_id"] for r in c.get("/v1/ingest-runs").json()] == ["b", "a", "c"]
    assert [r["run_id"] for r in c.get("/v1/ingest-runs?job=sec_tickers&limit=1").json()] == ["b"]
    assert c.get("/v1/ingest-runs?limit=201").status_code == 422


def test_counts(db_path):
    _, c = make(db_path, FakeRunner())
    got = c.get("/v1/ops/counts").json()
    assert got == {"companies": 0, "tickers": 0, "filings": 0, "facts": 0, "public_float": 0}


def test_default_runner_calls_recon_ingest(db_path, monkeypatch):
    """No fake: the API builds recon settings for its own DB and calls pipeline.ingest."""
    calls = []
    monkeypatch.setenv("FINAGENT_SEC_USER_AGENT", "FinAgent test@example.com")
    monkeypatch.setattr(
        "finagent.recon.pipeline.ingest",
        lambda s, job, lock_wait: calls.append((s.db_path, job, lock_wait)),
    )
    app = create_app(ApiSettings(db_path=db_path, job_lock_wait=7, _env_file=None))
    TestClient(base_url="http://localhost", app=app).post("/v1/jobs/sec_frames/runs")
    assert app.state.jobs.wait(5)
    assert calls == [(db_path, "sec_frames", 7)]


def test_shutdown_marks_this_process_running_job_interrupted(db_path):
    runner = FakeRunner()
    app, c = make(db_path, runner)
    with c:
        c.post("/v1/jobs/sec_frames/runs")
        assert runner.started.wait(5)
        con = connect(db_path)  # the runner's own record, as the real recon runner writes it
        con.execute(
            "INSERT INTO ingest_runs (run_id, job, started_at, status) VALUES "
            "('live', 'sec_frames', ?, 'running')",
            [app.state.jobs.active.started_at],
        )
        con.close()
    runner.release.set()
    con = connect(db_path)
    rows = dict(con.execute("SELECT run_id, status FROM ingest_runs WHERE job = 'sec_frames'"))
    sample = con.execute("SELECT error_sample FROM ingest_runs WHERE run_id = 'live'").fetchone()[0]
    con.close()
    assert rows == {"live": "failed", "c": "partial"}  # older run untouched
    assert sample == "interrupted: API stopped"
    con = connect(db_path)
    other = con.execute("SELECT status FROM ingest_runs WHERE run_id = 'b'").fetchone()[0]
    con.close()
    assert other == "running"  # sec_tickers' row was not started by this process


def test_ingest_runs_filter_by_status_and_time(db_path):
    _, c = make(db_path, FakeRunner())
    got = c.get("/v1/ingest-runs", params={"status": "ok"}).json()
    assert [r["run_id"] for r in got] == ["a"]
    since = c.get("/v1/ingest-runs", params={"since": "2026-11-01T10:30:00Z"}).json()
    assert [r["run_id"] for r in since] == ["b"]
    until = c.get("/v1/ingest-runs", params={"until": "2026-11-01T10:00:00Z"}).json()
    assert [r["run_id"] for r in until] == ["c"]
    assert c.get("/v1/ingest-runs?status=weird").status_code == 422


def test_ingest_runs_sorting(db_path):
    _, c = make(db_path, FakeRunner())

    def ids(**params):
        return [r["run_id"] for r in c.get("/v1/ingest-runs", params=params).json()]

    assert ids() == ["b", "a", "c"]  # newest first by default
    assert ids(sort="started_at", order="asc") == ["c", "a", "b"]
    assert ids(sort="duration", order="desc") == ["c", "a", "b"]  # 60s, 5s, unfinished last
    assert ids(sort="rows_written", order="asc") == ["c", "a", "b"]  # 5, 10, null last
    assert c.get("/v1/ingest-runs?sort=nope").status_code == 422
