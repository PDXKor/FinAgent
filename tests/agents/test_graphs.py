import asyncio

import pytest

from finagent_agents.registry import load_workflows
from finagent_agents.runner import Runner

from .conftest import ai, call, first_human, tool_results

pytestmark = pytest.mark.component

WORKFLOWS = load_workflows()


def run(runner, name, inputs):
    return asyncio.run(runner.run(name, inputs))


def test_ping_returns_model_text(data, scripted):
    llm = scripted(lambda msgs: ai("pong: " + first_human(msgs)))
    rec = run(Runner(WORKFLOWS, data, make_llm=lambda b: llm), "ping", {"text": "hi"})
    assert (rec.status, rec.output) == ("ok", "pong: text: hi")


def test_static_system_prompt_is_first_and_cached(data, scripted):
    seen = []
    llm = scripted(lambda msgs: (seen.append(msgs), ai("ok"))[1])
    run(Runner(WORKFLOWS, data, make_llm=lambda b: llm), "ping", {"text": "hi"})
    system = seen[0][0]
    assert system.type == "system"
    assert system.content[0]["text"] == WORKFLOWS["ping"].nodes["agent"].system
    assert system.content[0]["cache_control"] == {"type": "ephemeral"}


def test_company_brief_calls_tool_then_answers(data, scripted):
    def respond(msgs):
        results = tool_results(msgs)
        if not results:
            return call("get_company", {"ticker": "aapl"})
        return ai(f"brief from {results[0].content}")

    llm = scripted(respond)
    rec = run(Runner(WORKFLOWS, data, make_llm=lambda b: llm), "company_brief", {"ticker": "AAPL"})
    assert rec.status == "ok", rec.error
    assert "Apple Inc." in rec.output
    assert llm.calls == 2


def test_screen_then_brief_fans_out_per_ticker(data, scripted):
    screener = scripted(lambda msgs: ai(f"note on {first_human(msgs)}"), delay=0.05)
    writer_input = []
    writer = scripted(lambda msgs: (writer_input.append(first_human(msgs)), ai("final"))[1])
    llms = {"screener@1": screener, "brief_writer@1": writer}
    tickers = ["AAPL", "TSLA", "MSFT"]

    rec = run(
        Runner(WORKFLOWS, data, make_llm=lambda b: llms[b.prompt]),
        "screen_then_brief",
        {"tickers": tickers},
    )

    assert (rec.status, rec.output) == ("ok", "final"), rec.error
    assert screener.calls == 3
    assert screener.peak > 1  # screens ran in parallel
    assert all(f"note on ticker: {t}" in writer_input[0] for t in tickers)
    assert rec.input_tokens == 10 * 4  # usage counted inside subgraphs too


def test_two_agents_each_do_their_own_work(data, scripted):
    """Screener fetches financials; the writer has no such tool, so its brief can only carry
    the screener's figures, and it adds the company profile from its own tool."""

    def screener_respond(msgs):
        results = tool_results(msgs)
        if not results:
            return call("get_financials", {"ticker": "AAPL"})
        return ai(f"WATCH {results[0].content}")

    def writer_respond(msgs):
        results = tool_results(msgs)
        if not results:
            return call("get_company", {"ticker": "AAPL"})
        return ai(f"{results[0].content} || {first_human(msgs)}")

    screener, writer = scripted(screener_respond), scripted(writer_respond)
    llms = {"screener@1": screener, "brief_writer@1": writer}

    rec = run(
        Runner(WORKFLOWS, data, make_llm=lambda b: llms[b.prompt]),
        "screen_then_brief",
        {"tickers": ["AAPL"]},
    )

    assert rec.status == "ok", rec.error
    assert (screener.calls, writer.calls) == (2, 2)  # each: tool call, then answer
    assert "Apple Inc." in rec.output  # writer's own tool
    assert "94000000000.0" in rec.output  # screener's figure, carried via its note
