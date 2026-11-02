import asyncio
from dataclasses import replace

import pytest

from finagent_agents.registry import InputError, WorkflowError, load_workflows
from finagent_agents.runner import Runner

from .conftest import ai, first_human

pytestmark = pytest.mark.component

WORKFLOWS = load_workflows()


def echo(msgs):
    return ai(f"echo {first_human(msgs)}")


def with_ping(**changes):
    return {**WORKFLOWS, "ping": replace(WORKFLOWS["ping"], **changes)}


def test_run_lifecycle_saved_with_bindings_and_tokens(data, scripted):
    statuses = []
    save = data.save_run

    async def recording_save(r):
        statuses.append(r.status)
        await save(r)

    data.save_run = recording_save
    llm = scripted(echo)

    rec = asyncio.run(Runner(WORKFLOWS, data, make_llm=lambda b: llm).run("ping", {"text": "x"}))

    assert statuses == ["queued", "running", "ok"]
    assert data.runs[rec.run_id] == rec
    assert rec.bindings == WORKFLOWS["ping"].describe()
    assert (rec.input_tokens, rec.output_tokens) == (10, 5)
    assert rec.finished_at >= rec.started_at


def test_global_cap_limits_concurrent_runs_and_keeps_state_isolated(data, scripted):
    llm = scripted(echo, delay=0.05)
    runner = Runner(WORKFLOWS, data, make_llm=lambda b: llm, max_runs=3)
    texts = [f"t{i}" for i in range(9)]

    recs = asyncio.run(runner.run_many("ping", [{"text": t} for t in texts]))

    assert llm.peak == 3
    assert [r.output for r in recs] == [f"echo text: {t}" for t in texts]
    assert len({r.run_id for r in recs}) == 9


def test_per_workflow_cap(data, scripted):
    llm = scripted(echo, delay=0.05)
    runner = Runner(with_ping(max_concurrency=2), data, make_llm=lambda b: llm, max_runs=10)
    asyncio.run(runner.run_many("ping", [{"text": str(i)} for i in range(6)]))
    assert llm.peak == 2


def test_one_failure_does_not_affect_others(data, scripted):
    def respond(msgs):
        if "BAD" in first_human(msgs):
            raise RuntimeError("boom")
        return ai("ok")

    llm = scripted(respond)
    runner = Runner(WORKFLOWS, data, make_llm=lambda b: llm)
    recs = asyncio.run(runner.run_many("ping", [{"text": "a"}, {"text": "BAD"}, {"text": "c"}]))
    assert [r.status for r in recs] == ["ok", "failed", "ok"]
    assert "boom" in recs[1].error
    assert data.runs[recs[1].run_id].status == "failed"


def test_timeout_marks_run(data, scripted):
    llm = scripted(echo, delay=1.0)
    runner = Runner(with_ping(timeout_s=0.05), data, make_llm=lambda b: llm)
    rec = asyncio.run(runner.run("ping", {"text": "x"}))
    assert rec.status == "timeout"
    assert "0.05" in rec.error


def test_invalid_inputs_raise_before_any_run_is_saved(data, scripted):
    runner = Runner(WORKFLOWS, data, make_llm=lambda b: scripted(echo))
    with pytest.raises(InputError):
        asyncio.run(runner.run("ping", {}))
    with pytest.raises(InputError):
        asyncio.run(runner.run_many("ping", [{"text": "ok"}, {"txt": "typo"}]))
    assert data.runs == {}


def test_unknown_workflow_raises(data, scripted):
    runner = Runner(WORKFLOWS, data, make_llm=lambda b: scripted(echo))
    with pytest.raises(WorkflowError, match="nope"):
        asyncio.run(runner.run("nope", {}))


def test_final_save_is_retried_then_succeeds(data, scripted, monkeypatch):
    from finagent_agents import runner as runner_mod

    monkeypatch.setattr(runner_mod, "SAVE_BACKOFF_S", 0)
    save, calls = data.save_run, []

    async def flaky(r):
        calls.append(r.status)
        if r.status == "ok" and calls.count("ok") < 3:
            raise ConnectionError("blip")
        await save(r)

    data.save_run = flaky
    rec = asyncio.run(
        Runner(WORKFLOWS, data, make_llm=lambda b: scripted(echo)).run("ping", {"text": "x"})
    )
    assert calls == ["queued", "running", "ok", "ok", "ok"]
    assert data.runs[rec.run_id].status == "ok"


def test_final_save_failure_logs_the_result(data, scripted, monkeypatch, caplog):
    from finagent_agents import runner as runner_mod

    monkeypatch.setattr(runner_mod, "SAVE_BACKOFF_S", 0)
    save = data.save_run

    async def broken_final(r):
        if r.status == "ok":
            raise ConnectionError("down")
        await save(r)

    data.save_run = broken_final
    with pytest.raises(ConnectionError):
        asyncio.run(
            Runner(WORKFLOWS, data, make_llm=lambda b: scripted(echo)).run("ping", {"text": "x"})
        )
    assert "not saved" in caplog.text and "echo text: x" in caplog.text
