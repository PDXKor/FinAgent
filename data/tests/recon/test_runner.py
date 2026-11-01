from typing import ClassVar

import httpx
import pytest

from finagent.data.db import connect
from finagent.recon.jobs.base import Request
from finagent.recon.runner import RateLimiter, Runner

pytestmark = pytest.mark.component


class FakeJob:
    name = "fake"
    source = "sec"
    keys: ClassVar[dict[str, list[str]]] = {"companies": ["cik"]}

    def __init__(self, urls=("https://x/1",), explode_plan=False):
        self.urls = urls
        self.explode_plan = explode_plan

    def plan(self, con):
        if self.explode_plan:
            raise RuntimeError("plan boom")
        return [Request(u, u.rsplit("/", 1)[1]) for u in self.urls]

    def parse(self, req, body):
        if body == b"bad":
            raise ValueError("cannot parse")
        return {"companies": [{"cik": req.key, "name": body.decode()}]}


class Env:
    def __init__(self, tmp_path, handler):
        self.con = connect(tmp_path / "t.duckdb")
        self.sleeps = []
        self.client = httpx.Client(transport=httpx.MockTransport(handler))
        self.runner = Runner(
            self.con, self.client, tmp_path / "raw", rates={"sec": 1000}, sleep=self.sleeps.append
        )

    def runs(self):
        return self.con.execute(
            "SELECT status, requests, rows_written, errors, error_sample FROM ingest_runs"
        ).fetchall()


@pytest.fixture
def env(tmp_path):
    made = []

    def make(handler):
        e = Env(tmp_path, handler)
        made.append(e)
        return e

    yield make
    for e in made:
        e.con.close()


def ok(request):
    return httpx.Response(200, content=b"Acme")


def test_run_writes_rows_logs_run_and_saves_raw(env, tmp_path):
    e = env(ok)
    res = e.runner.run(FakeJob())
    assert res.status == "ok"
    assert e.con.execute("SELECT cik, name FROM companies").fetchall() == [("1", "Acme")]
    assert e.runs() == [("ok", 1, 1, 0, None)]
    assert len(list((tmp_path / "raw" / "sec" / "fake" / "1").glob("*.json"))) == 1
    state = e.con.execute("SELECT job, key, last_status FROM source_state").fetchall()
    assert state == [("fake", "1", 200)]


def test_run_is_idempotent(env):
    e = env(ok)
    e.runner.run(FakeJob())
    e.runner.run(FakeJob())
    assert e.con.execute("SELECT count(*) FROM companies").fetchone()[0] == 1
    assert len(e.runs()) == 2


def test_retries_429_with_backoff_then_succeeds(env):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429) if len(calls) < 3 else httpx.Response(200, content=b"Acme")

    e = env(handler)
    assert e.runner.run(FakeJob()).status == "ok"
    assert len(calls) == 3
    assert e.sleeps == [1, 2]


def test_gives_up_after_max_attempts_and_marks_failed(env):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    e = env(handler)
    res = e.runner.run(FakeJob())
    assert (res.status, res.errors) == ("failed", 1)
    assert len(calls) == 3
    status, _, rows, errors, sample = e.runs()[0]
    assert (status, rows, errors) == ("failed", 0, 1)
    assert "503" in sample


def test_client_error_is_not_retried(env):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404)

    e = env(handler)
    assert e.runner.run(FakeJob()).status == "failed"
    assert len(calls) == 1


def test_transport_error_is_retried(env):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(200, content=b"Acme")

    e = env(handler)
    assert e.runner.run(FakeJob()).status == "ok"


def test_one_bad_request_makes_run_partial_and_others_still_land(env):
    def handler(request):
        return httpx.Response(200, content=b"bad" if request.url.path == "/2" else b"Acme")

    e = env(handler)
    res = e.runner.run(FakeJob(urls=("https://x/1", "https://x/2", "https://x/3")))
    assert (res.status, res.requests, res.errors, res.rows_written) == ("partial", 3, 1, 2)
    assert e.con.execute("SELECT count(*) FROM companies").fetchone()[0] == 2


def test_plan_exception_marks_run_failed_and_reraises(env):
    e = env(ok)
    with pytest.raises(RuntimeError, match="plan boom"):
        e.runner.run(FakeJob(explode_plan=True))
    assert e.runs()[0][0] == "failed"


def test_empty_plan_is_ok(env):
    e = env(ok)
    assert e.runner.run(FakeJob(urls=())).status == "ok"


def test_rate_limiter_spaces_calls():
    now = [0.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    rl = RateLimiter(5, clock=lambda: now[0], sleep=sleep)
    rl.acquire()
    rl.acquire()
    rl.acquire()
    assert sleeps == pytest.approx([0.2, 0.2])


def counting_env(env):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=b"Acme")

    return env(handler), calls


def test_reparse_rebuilds_rows_from_newest_raw_file_without_fetching(env, tmp_path):
    e, calls = counting_env(env)
    e.runner.run(FakeJob())
    e.con.execute("DELETE FROM companies")
    newer = tmp_path / "raw" / "sec" / "fake" / "1" / "29990101T000000.json"
    newer.write_bytes(b"Newer")
    res = e.runner.reparse(FakeJob())
    assert (res.status, res.requests, res.rows_written, res.errors) == ("ok", 1, 1, 0)
    assert e.con.execute("SELECT cik, name FROM companies").fetchall() == [("1", "Newer")]
    assert len(calls) == 1  # only the original fetch


def test_reparse_logs_run_under_its_own_job_name(env):
    e, _ = counting_env(env)
    e.runner.run(FakeJob())
    e.runner.reparse(FakeJob())
    rows = e.con.execute("SELECT job FROM ingest_runs ORDER BY started_at").fetchall()
    jobs = [r[0] for r in rows]
    assert jobs == ["fake", "fake:reparse"]


def test_reparse_does_not_touch_source_state(env):
    e, _ = counting_env(env)
    e.runner.run(FakeJob())
    before = e.con.execute("SELECT * FROM source_state").fetchall()
    e.runner.reparse(FakeJob())
    assert e.con.execute("SELECT * FROM source_state").fetchall() == before


def test_reparse_bad_file_makes_run_partial_and_others_still_load(env, tmp_path):
    e, _ = counting_env(env)
    e.runner.run(FakeJob(urls=("https://x/1", "https://x/2")))
    (tmp_path / "raw" / "sec" / "fake" / "2" / "29990101T000000.json").write_bytes(b"bad")
    e.con.execute("DELETE FROM companies")
    res = e.runner.reparse(FakeJob())
    assert (res.status, res.requests, res.errors, res.rows_written) == ("partial", 2, 1, 1)


def test_reparse_with_no_raw_files_is_ok_and_empty(env):
    e, _ = counting_env(env)
    res = e.runner.reparse(FakeJob())
    assert (res.status, res.requests) == ("ok", 0)


class OptionalJob(FakeJob):
    def plan(self, con):
        return [Request(u, u.rsplit("/", 1)[1], optional=True) for u in self.urls]


def test_optional_request_404_is_skipped_without_error_or_raw_file(env, tmp_path):
    e = env(lambda request: httpx.Response(404))
    res = e.runner.run(OptionalJob())
    assert (res.status, res.requests, res.errors, res.rows_written) == ("ok", 1, 0, 0)
    assert not (tmp_path / "raw").exists()
    assert e.con.execute("SELECT count(*) FROM source_state").fetchone()[0] == 0


def test_optional_request_still_fails_on_server_errors(env):
    e = env(lambda request: httpx.Response(500))
    assert e.runner.run(OptionalJob()).status == "failed"
