from datetime import date

import pytest
from fastapi.testclient import TestClient

from finagent.api.app import create_app
from finagent.api.config import ApiSettings
from finagent.data.db import connect, upsert

pytestmark = pytest.mark.component

CIK = "0000320193"
RUN = {"workflow": "ping", "status": "running", "inputs": {"text": "hi"},
       "started_at": "2026-11-01T12:00:00+00:00"}  # fmt: skip


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    con = connect(path)
    upsert(con, "tickers", [{"ticker": "AAPL", "cik": CIK, "exchange": "Nasdaq"}], ["ticker"])
    upsert(con, "companies", [{"cik": CIK, "name": "Apple Inc."}], ["cik"])
    upsert(
        con,
        "facts",
        [
            {
                "cik": CIK,
                "taxonomy": "us-gaap",
                "concept": "Revenues",
                "unit": "USD",
                "period_start": date(2024, 1, 1),
                "period_end": date(2024, 12, 31),
                "value": 9.5,
                "fy": 2024,
                "form": "10-K",
                "accession_no": "k24",
                "filed_date": date(2025, 2, 1),
            },
        ],
        ["cik", "taxonomy", "concept", "unit", "period_start", "period_end", "accession_no"],
    )
    con.close()
    return path


@pytest.fixture
def client(db_path):
    return TestClient(
        base_url="http://localhost",
        app=create_app(ApiSettings(db_path=db_path, api_token=None, _env_file=None)),
    )


def test_health(client):
    assert client.get("/v1/health").json() == {"status": "ok"}


def test_company_found_and_404(client):
    got = client.get("/v1/companies/aapl")
    assert got.status_code == 200
    assert got.json()["name"] == "Apple Inc." and got.json()["cik"] == CIK
    assert client.get("/v1/companies/ZZZZ").status_code == 404


def test_financials_shape_and_limit_bounds(client):
    got = client.get("/v1/companies/AAPL/financials").json()
    assert got[0]["fiscal_year"] == 2024
    assert got[0]["period_end"] == "2024-12-31"
    assert got[0]["revenue"] == 9.5
    assert client.get("/v1/companies/ZZZZ/financials").json() == []
    assert client.get("/v1/companies/AAPL/financials?limit=21").status_code == 422


def test_put_agent_run_is_idempotent_upsert(client):
    assert client.put("/v1/agent-runs/r1", json=RUN).status_code == 204
    done = {**RUN, "status": "ok", "output": "brief", "input_tokens": 7}
    assert client.put("/v1/agent-runs/r1", json=done).status_code == 204
    got = client.get("/v1/agent-runs/r1").json()
    assert (got["status"], got["output"], got["input_tokens"]) == ("ok", "brief", 7)
    assert got["inputs"] == {"text": "hi"}
    assert client.get("/v1/agent-runs/nope").status_code == 404


def test_put_agent_run_rejects_bad_status(client):
    assert client.put("/v1/agent-runs/r1", json={**RUN, "status": "weird"}).status_code == 422


def test_write_while_locked_returns_503(db_path):
    app = create_app(ApiSettings(db_path=db_path, api_lock_wait=0, _env_file=None))
    holder = connect(db_path)
    holder.execute("BEGIN IMMEDIATE")
    try:
        got = TestClient(base_url="http://localhost", app=app).put("/v1/agent-runs/r1", json=RUN)
    finally:
        holder.rollback()
        holder.close()
    assert got.status_code == 503
    assert got.headers["Retry-After"] == "1"


def test_token_enforced_when_set(db_path):
    app = create_app(ApiSettings(db_path=db_path, api_token="s3cret", _env_file=None))
    c = TestClient(base_url="http://localhost", app=app)
    assert c.get("/v1/health").status_code == 401
    assert c.get("/v1/health", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/v1/health", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_blank_token_means_no_auth(db_path, monkeypatch):
    monkeypatch.setenv("FINAGENT_API_TOKEN", "")
    c = TestClient(
        base_url="http://localhost", app=create_app(ApiSettings(db_path=db_path, _env_file=None))
    )
    assert c.get("/v1/health").status_code == 200


def test_list_agent_runs_filters_and_pages(client):
    for i, (wf, status) in enumerate(
        [("ping", "ok"), ("brief", "running"), ("ping", "cancelled"), ("ping", "running")]
    ):
        run = {**RUN, "workflow": wf, "status": status, "started_at": f"2026-11-01T12:0{i}:00Z"}
        assert client.put(f"/v1/agent-runs/r{i}", json=run).status_code == 204

    page = client.get("/v1/agent-runs?limit=3").json()
    assert [r["run_id"] for r in page["items"]] == ["r3", "r2", "r1"]
    assert page["next"] == "2026-11-01T12:01:00+00:00|r1"
    rest = client.get("/v1/agent-runs", params={"limit": 3, "cursor": page["next"]}).json()
    assert [r["run_id"] for r in rest["items"]] == ["r0"] and rest["next"] is None

    running = client.get("/v1/agent-runs?status=running&workflow=ping").json()["items"]
    assert [r["run_id"] for r in running] == ["r3"]
    assert running[0]["inputs"] == {"text": "hi"}
    assert client.get("/v1/agent-runs?status=weird").status_code == 422


def test_paging_does_not_skip_runs_with_equal_start_times(client):
    for i in range(5):
        assert client.put(f"/v1/agent-runs/r{i}", json=RUN).status_code == 204  # same started_at
    seen, cursor = [], None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = client.get("/v1/agent-runs", params=params).json()
        seen += [r["run_id"] for r in page["items"]]
        if not (cursor := page["next"]):
            break
    assert seen == ["r4", "r3", "r2", "r1", "r0"]
    assert client.get("/v1/agent-runs?cursor=junk").status_code == 422


def test_queued_status_accepted(client):
    assert client.put("/v1/agent-runs/q", json={**RUN, "status": "queued"}).status_code == 204
    assert [r["run_id"] for r in client.get("/v1/agent-runs?status=queued").json()["items"]] == [
        "q"
    ]


def test_cross_site_browser_requests_refused(client):
    for site in ("cross-site", "same-site"):
        got = client.post("/v1/jobs/sec_tickers/runs", headers={"Sec-Fetch-Site": site})
        assert got.status_code == 403
    assert client.get("/v1/health", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.get("/v1/health", headers={"Sec-Fetch-Site": "none"}).status_code == 200


def test_unknown_host_refused(db_path):
    app = create_app(ApiSettings(db_path=db_path, _env_file=None))
    assert TestClient(base_url="http://evil.example", app=app).get("/v1/health").status_code == 400
    c = TestClient(
        base_url="http://data:8765",
        app=create_app(ApiSettings(db_path=db_path, api_allowed_hosts=["data"], _env_file=None)),
    )
    assert c.get("/v1/health").status_code == 200


def test_docs_only_without_token(db_path):
    open_app = create_app(ApiSettings(db_path=db_path, _env_file=None))
    assert (
        TestClient(base_url="http://localhost", app=open_app).get("/openapi.json").status_code
        == 200
    )
    locked = create_app(ApiSettings(db_path=db_path, api_token="t", _env_file=None))
    assert (
        TestClient(base_url="http://localhost", app=locked).get("/openapi.json").status_code == 404
    )


def test_unexpected_database_error_is_logged(client, monkeypatch, caplog):
    import sqlite3

    def broken(con, ticker):
        raise sqlite3.OperationalError("no such column: c.sic")

    monkeypatch.setattr("finagent.api.app.get_company", broken)
    got = client.get("/v1/companies/AAPL")
    assert got.status_code == 500 and got.json() == {"detail": "database error"}
    assert "no such column" in caplog.text


def test_no_token_warning_only_when_reachable_beyond_localhost(db_path, caplog):
    with TestClient(
        base_url="http://localhost", app=create_app(ApiSettings(db_path=db_path, _env_file=None))
    ):
        pass
    assert "FINAGENT_API_TOKEN is unset" not in caplog.text
    exposed = create_app(ApiSettings(db_path=db_path, api_host="0.0.0.0", _env_file=None))
    with TestClient(base_url="http://localhost", app=exposed):
        pass
    assert "FINAGENT_API_TOKEN is unset" in caplog.text
