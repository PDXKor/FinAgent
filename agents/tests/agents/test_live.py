"""Real Claude calls. Costs money; skipped unless ANTHROPIC_API_KEY is set."""

import asyncio
import os

import pytest

from finagent_agents.registry import load_workflows
from finagent_agents.runner import Runner

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"),
]


def test_company_brief_against_claude(data):
    lookups = []
    get_company = data.get_company

    async def recording_get_company(t):
        lookups.append(t)
        return await get_company(t)

    data.get_company = recording_get_company

    rec = asyncio.run(Runner(load_workflows(), data).run("company_brief", {"ticker": "AAPL"}))

    assert rec.status == "ok", rec.error
    assert lookups, "Claude never called get_company"
    assert "Apple" in rec.output
    assert rec.input_tokens > 0
