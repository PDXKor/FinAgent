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
    return TestClient(create_app(ApiSettings(db_path=db_path, api_token=None, _env_file=None)))


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
        got = TestClient(app).put("/v1/agent-runs/r1", json=RUN)
    finally:
        holder.rollback()
        holder.close()
    assert got.status_code == 503
    assert got.headers["Retry-After"] == "1"


def test_token_enforced_when_set(db_path):
    app = create_app(ApiSettings(db_path=db_path, api_token="s3cret", _env_file=None))
    c = TestClient(app)
    assert c.get("/v1/health").status_code == 401
    assert c.get("/v1/health", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/v1/health", headers={"Authorization": "Bearer s3cret"}).status_code == 200
