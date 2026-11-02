import asyncio

import pytest

from finagent_agents.events import EventHub

pytestmark = pytest.mark.unit


async def collect(hub, run_id, **kw):
    return [e async for e in hub.subscribe(run_id, **kw)]


def test_subscriber_gets_backlog_then_live_events_until_close():
    async def go():
        hub = EventHub()
        s = hub.open("r1")
        s.emit("a", n=1)
        task = asyncio.create_task(collect(hub, "r1"))
        await asyncio.sleep(0)
        s.emit("b", n=2)
        hub.close("r1")
        s.emit("ignored")
        return await task

    events = asyncio.run(go())
    assert [(e.id, e.type, e.data) for e in events] == [(1, "a", {"n": 1}), (2, "b", {"n": 2})]


def test_replay_after_id_and_after_close():
    async def go():
        hub = EventHub()
        s = hub.open("r1")
        for t in "abc":
            s.emit(t)
        hub.close("r1")
        return await collect(hub, "r1", after=1)

    assert [e.type for e in asyncio.run(go())] == ["b", "c"]


def test_keepalive_yields_none_during_silence():
    async def go():
        hub = EventHub()
        hub.open("r1")
        got = []
        async for e in hub.subscribe("r1", keepalive=0.01):
            got.append(e)
            if len(got) == 2:
                hub.close("r1")
        return got

    assert asyncio.run(go()) == [None, None]


def test_retains_only_newest_finished_streams_and_never_open_ones():
    hub = EventHub(retain=2)
    hub.open("live")
    for r in ("r1", "r2", "r3"):
        hub.open(r)
        hub.close(r)
    assert hub.get("r1") is None
    assert hub.get("r2") and hub.get("r3") and hub.get("live")
    with pytest.raises(KeyError):
        asyncio.run(collect(hub, "r1"))


def test_run_ending_during_backlog_replay_loses_nothing():
    async def go():
        hub = EventHub()
        s = hub.open("r1")
        s.emit("a")
        s.emit("b")
        got = []
        async for e in hub.subscribe("r1"):
            got.append(e.type)
            if e.type == "a":  # still replaying the backlog when the run finishes
                s.emit("done")
                hub.close("r1")
        return got

    assert asyncio.run(go()) == ["a", "b", "done"]
