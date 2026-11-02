import asyncio
import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from finagent_agents import data as data_mod
from finagent_agents.data import HttpDataLayer, RunRecord

BASE = "http://finagent-data"


def layer(handler) -> HttpDataLayer:
    return HttpDataLayer(BASE, token="t0k", transport=httpx.MockTransport(handler))


def run_with(handler, call):
    async def go():
        async with layer(handler) as d:
            return await call(d)

    return asyncio.run(go())


@pytest.mark.unit
def test_get_company_hits_v1_with_token_and_maps_404():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/v1/companies/AAPL":
            return httpx.Response(200, json={"ticker": "AAPL", "cik": "0000320193"})
        return httpx.Response(404, json={"detail": "unknown"})

    assert run_with(handler, lambda d: d.get_company("AAPL"))["cik"] == "0000320193"
    assert run_with(handler, lambda d: d.get_company("ZZZZ")) is None
    assert seen[0].headers["Authorization"] == "Bearer t0k"


@pytest.mark.unit
def test_get_financials_passes_limit():
    def handler(req):
        assert req.url.path == "/v1/companies/AAPL/financials"
        return httpx.Response(200, json=[{"limit": req.url.params["limit"]}])

    assert run_with(handler, lambda d: d.get_financials("AAPL", limit=3)) == [{"limit": "3"}]


@pytest.mark.unit
def test_save_run_puts_json_body_by_run_id():
    bodies = []

    def handler(req):
        assert (req.method, req.url.path) == ("PUT", "/v1/agent-runs/r1")
        bodies.append(json.loads(req.content))
        return httpx.Response(204)

    started = datetime(2026, 11, 1, 12, tzinfo=UTC)
    run = RunRecord("r1", "ping", {"text": "hi"}, "ok", started, output={"x": object()})
    run_with(handler, lambda d: d.save_run(run))

    body = bodies[0]
    assert "run_id" not in body
    assert body["started_at"] == "2026-11-01T12:00:00+00:00"
    assert body["inputs"] == {"text": "hi"}
    assert body["output"]["x"].startswith("<object")  # non-JSON output degrades to str()


@pytest.mark.unit
def test_busy_503_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(data_mod, "BUSY_BACKOFF_S", 0)
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=[])

    assert run_with(handler, lambda d: d.get_financials("AAPL")) == []
    assert len(calls) == 3


@pytest.mark.unit
def test_persistent_503_raises(monkeypatch):
    monkeypatch.setattr(data_mod, "BUSY_BACKOFF_S", 0)
    with pytest.raises(httpx.HTTPStatusError):
        run_with(lambda req: httpx.Response(503), lambda d: d.get_financials("AAPL"))


DATA_URL = os.environ.get("FINAGENT_AGENTS_DATA_URL")


@pytest.mark.contract
@pytest.mark.skipif(not DATA_URL, reason="FINAGENT_AGENTS_DATA_URL not set")
def test_round_trip_against_running_api():
    """Needs `finagent-data serve` with data from `recon`. Writes one throwaway agent_runs row."""

    async def go():
        async with HttpDataLayer(DATA_URL, os.environ.get("FINAGENT_AGENTS_DATA_TOKEN")) as d:
            assert await d.get_company("ZZZZ-NOT-A-TICKER") is None
            run = RunRecord(f"contract-{uuid4().hex}", "contract", {}, "ok", datetime.now(UTC))
            await d.save_run(run)
            return await d.get_financials("ZZZZ-NOT-A-TICKER")

    assert asyncio.run(go()) == []


@pytest.mark.unit
def test_list_runs_follows_pages_and_parses_records():
    def item(i):
        return {"run_id": f"r{i}", "workflow": "ping", "status": "running", "inputs": {},
                "output": None, "error": None, "bindings": {}, "input_tokens": 0,
                "output_tokens": 0, "cache_read_tokens": 0, "finished_at": None,
                "started_at": f"2026-11-01T12:0{i}:00Z"}  # fmt: skip

    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        if "cursor" not in request.url.params:
            page = {"items": [item(2), item(1)], "next": "c1"}
            return httpx.Response(200, json=page)
        return httpx.Response(200, json={"items": [item(0)], "next": None})

    runs = run_with(handler, lambda d: d.list_runs(status="running"))
    assert [r.run_id for r in runs] == ["r2", "r1", "r0"]
    assert runs[0].started_at == datetime(2026, 11, 1, 12, 2, tzinfo=UTC)
    assert seen[0] == {"limit": "200", "status": "running"}
    assert seen[1]["cursor"] == "c1"
