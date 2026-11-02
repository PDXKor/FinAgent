import asyncio
import json
import threading
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from finagent_agents.config import AgentSettings
from finagent_agents.data import RunRecord
from finagent_agents.registry import load_workflows
from finagent_agents.runner import INTERRUPTED
from finagent_agents.server import create_app

from .conftest import ScriptedChatModel, ai, call, first_human, tool_results

pytestmark = pytest.mark.component

WORKFLOWS = load_workflows()


def settings(**kw) -> AgentSettings:
    return AgentSettings(_env_file=None, **kw)


def client(data, respond, delay=0.0, **kw) -> TestClient:
    llm = ScriptedChatModel(respond=respond, delay=delay)
    app = create_app(settings(**kw), WORKFLOWS, data=data, make_llm=lambda b: llm)
    return TestClient(app, base_url="http://localhost")


def events(c: TestClient, run_id: str, headers=None) -> list[tuple[int, str, dict]]:
    """Read the SSE stream to the end: (id, type, data) per event."""
    out, cur = [], {}
    with c.stream("GET", f"/v1/runs/{run_id}/events", headers=headers or {}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if not line:
                if cur:
                    out.append((int(cur["id"]), cur["event"], json.loads(cur["data"])))
                cur = {}
            elif not line.startswith(":"):
                key, _, value = line.partition(": ")
                cur[key] = value
    if cur:  # a final event without a trailing blank line
        out.append((int(cur["id"]), cur["event"], json.loads(cur["data"])))
    return out


def echo(msgs):
    return ai(f"echo {first_human(msgs)}")


def test_workflow_catalog(data):
    with client(data, echo) as c:
        got = {w["name"]: w for w in c.get("/v1/workflows").json()}
    assert set(got) == set(WORKFLOWS)
    assert got["ping"]["input"] == {"text": "str"}
    assert got["screen_then_brief"]["nodes"]["screener"]["model"] == "claude-haiku-5-5"
    assert got["company_brief"]["nodes"]["agent"]["tools"] == ["get_company", "get_financials"]


def test_start_streams_events_and_saves_run(data):
    with client(data, echo) as c:
        started = c.post("/v1/workflows/ping/runs", json={"inputs": {"text": "hi"}})
        assert started.status_code == 202
        body = started.json()
        assert body["status"] == "queued" and body["started_at"].endswith("Z")
        evs = events(c, body["run_id"])

    types = [t for _, t, _ in evs]
    assert types[:2] == ["run_start", "running"] and types[-1] == "done"
    assert {"node_start", "llm_start", "llm_end", "node_end"} <= set(types)
    assert [i for i, _, _ in evs] == list(range(1, len(evs) + 1))
    assert evs[-1][2]["status"] == "ok" and evs[-1][2]["output_tokens"] == 5
    saved = data.runs[body["run_id"]]
    assert (saved.status, saved.output) == ("ok", "echo text: hi")


def test_tool_calls_appear_in_events_under_their_node(data):
    def respond(msgs):
        return ai("brief") if tool_results(msgs) else call("get_company", {"ticker": "AAPL"})

    with client(data, respond) as c:
        run_id = c.post("/v1/workflows/company_brief/runs", json={"inputs": {"ticker": "AAPL"}})
        evs = events(c, run_id.json()["run_id"])

    by_type = {t: d for _, t, d in evs}
    assert by_type["tool_start"]["tool"] == "get_company"
    assert json.loads(by_type["tool_start"]["input"]) == {"ticker": "AAPL"}
    assert "Apple Inc." in by_type["tool_end"]["output"]
    tools_node = next(d for _, t, d in evs if t == "node_start" and d["node"] == "tools")
    assert by_type["tool_start"]["parent"] == tools_node["span"]


def test_bad_input_422_unknown_workflow_404_unknown_run_404(data):
    with client(data, echo) as c:
        assert c.post("/v1/workflows/ping/runs", json={"inputs": {}}).status_code == 422
        assert c.post("/v1/workflows/nope/runs", json={"inputs": {}}).status_code == 404
        assert c.get("/v1/runs/nope/events").status_code == 404
        assert c.post("/v1/runs/nope/cancel").status_code == 404
    assert data.runs == {}


def test_cancel_stops_run_and_saves_cancelled(data):
    with client(data, echo, delay=30) as c:
        run_id = c.post("/v1/workflows/ping/runs", json={"inputs": {"text": "x"}}).json()["run_id"]
        assert c.get("/v1/health").json()["active_runs"] == 1
        assert c.post(f"/v1/runs/{run_id}/cancel").status_code == 202
        evs = events(c, run_id)
        assert c.get("/v1/health").json()["active_runs"] == 0
    assert evs[-1][1] == "done" and evs[-1][2]["status"] == "cancelled"
    assert data.runs[run_id].status == "cancelled" and data.runs[run_id].finished_at


def test_last_event_id_replays_only_newer_events(data):
    with client(data, echo) as c:
        run_id = c.post("/v1/workflows/ping/runs", json={"inputs": {"text": "x"}}).json()["run_id"]
        full = events(c, run_id)
        tail = events(c, run_id, headers={"Last-Event-ID": str(full[-3][0])})
    assert tail == full[-2:]


def test_shutdown_cancels_in_flight_runs(data):
    with client(data, echo, delay=30) as c:
        run_id = c.post("/v1/workflows/ping/runs", json={"inputs": {"text": "x"}}).json()["run_id"]
    assert data.runs[run_id].status == "cancelled"


def test_startup_marks_runs_left_running_as_failed(data):
    started = datetime(2026, 11, 1, tzinfo=UTC)
    stale = RunRecord("old", "ping", {"text": "x"}, "running", started)
    done = RunRecord("fine", "ping", {"text": "y"}, "ok", started, finished_at=started)
    asyncio.run(data.save_run(stale))
    asyncio.run(data.save_run(done))
    with client(data, echo):
        pass
    assert (data.runs["old"].status, data.runs["old"].error) == ("failed", INTERRUPTED)
    assert data.runs["old"].finished_at is not None
    assert data.runs["fine"].status == "ok"


def test_token_enforced_when_set(data):
    with client(data, echo, api_token="s3cret") as c:
        assert c.get("/v1/workflows").status_code == 401
        ok = c.get("/v1/workflows", headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200


def test_blank_token_means_no_auth(data, monkeypatch):
    monkeypatch.setenv("FINAGENT_AGENTS_API_TOKEN", "")
    with client(data, echo) as c:
        assert c.get("/v1/health").status_code == 200


def test_concurrent_subscribers_see_the_same_stream(data):
    with client(data, echo, delay=0.2) as c:
        run_id = c.post("/v1/workflows/ping/runs", json={"inputs": {"text": "x"}}).json()["run_id"]
        results: list = [None, None]

        def read(i):
            results[i] = events(c, run_id)

        threads = [threading.Thread(target=read, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
    assert results[0] == results[1] and results[0][-1][1] == "done"


def test_data_api_down_at_start_is_503(data, monkeypatch):
    import httpx

    async def down(run):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(data, "save_run", down)
    monkeypatch.setattr(data, "list_runs", lambda status=None, limit=200: _none())
    with client(data, echo) as c:
        got = c.post("/v1/workflows/ping/runs", json={"inputs": {"text": "x"}})
    assert got.status_code == 503 and "data API unavailable" in got.json()["detail"]


async def _none():
    return []


def test_cross_site_requests_and_unknown_hosts_refused(data):
    with client(data, echo) as c:
        got = c.post("/v1/runs/x/cancel", headers={"Sec-Fetch-Site": "cross-site"})
        assert got.status_code == 403
        assert c.get("/v1/health", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    llm = ScriptedChatModel(respond=echo)
    app = create_app(settings(), WORKFLOWS, data=data, make_llm=lambda b: llm)
    with TestClient(app, base_url="http://evil.example") as c:
        assert c.get("/v1/health").status_code == 400


def test_docs_only_without_token(data):
    with client(data, echo) as c:
        assert c.get("/openapi.json").status_code == 200
    with client(data, echo, api_token="t") as c:
        assert c.get("/openapi.json").status_code == 404


def test_startup_also_fails_runs_left_queued(data):
    stale = RunRecord("q", "ping", {"text": "x"}, "queued", datetime(2026, 11, 1, tzinfo=UTC))
    asyncio.run(data.save_run(stale))
    with client(data, echo):
        pass
    assert data.runs["q"].status == "failed"
