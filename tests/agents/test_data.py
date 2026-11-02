import asyncio
from datetime import UTC, datetime

import pytest

from finagent_agents.data import MemoryDataLayer, RunRecord

pytestmark = pytest.mark.unit


def test_get_company_returns_copy_or_none(data):
    async def go():
        company = await data.get_company("AAPL")
        company["name"] = "changed"
        assert (await data.get_company("AAPL"))["name"] == "Apple Inc."
        assert await data.get_company("ZZZZ") is None

    asyncio.run(go())


def test_get_financials_respects_limit():
    rows = [{"period_end": f"2025-0{i}-01"} for i in range(1, 6)]
    layer = MemoryDataLayer(financials={"X": rows})

    async def go():
        assert await layer.get_financials("X", limit=2) == rows[:2]
        assert await layer.get_financials("NOPE") == []

    asyncio.run(go())


def test_save_run_replaces_by_run_id():
    layer = MemoryDataLayer()
    run = RunRecord("r1", "ping", {"text": "hi"}, "running", datetime.now(UTC))

    async def go():
        await layer.save_run(run)
        run.status = "ok"
        await layer.save_run(run)

    asyncio.run(go())
    assert list(layer.runs) == ["r1"]
    assert layer.runs["r1"].status == "ok"
