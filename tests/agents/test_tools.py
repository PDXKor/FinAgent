import asyncio
import json

import pytest

from finagent_agents.data import MemoryDataLayer
from finagent_agents.tools import MAX_FINANCIAL_ROWS, TOOLS

pytestmark = pytest.mark.unit


def test_get_company_normalizes_ticker(data):
    tool = TOOLS["get_company"](data)
    assert tool.name == "get_company"
    assert asyncio.run(tool.ainvoke({"ticker": " aapl "}))["name"] == "Apple Inc."


def test_get_company_unknown_returns_empty(data):
    assert asyncio.run(TOOLS["get_company"](data).ainvoke({"ticker": "ZZZZ"})) == {}


def test_get_financials_caps_rows():
    rows = [{"period_end": str(i)} for i in range(50)]
    tool = TOOLS["get_financials"](MemoryDataLayer(financials={"X": rows}))
    assert len(asyncio.run(tool.ainvoke({"ticker": "x", "limit": 999}))) == MAX_FINANCIAL_ROWS
    assert len(asyncio.run(tool.ainvoke({"ticker": "x"}))) == 8


def test_tool_schemas_are_json_serializable(data):
    for factory in TOOLS.values():
        json.dumps(factory(data).tool_call_schema.model_json_schema())
