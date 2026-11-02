import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.rate_limiters import InMemoryRateLimiter

from finagent_agents.llm import make_llm
from finagent_agents.registry import NodeBinding

pytestmark = pytest.mark.unit


def test_make_llm_maps_binding(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    limiter = InMemoryRateLimiter(requests_per_second=1)
    binding = NodeBinding(model="claude-haiku-5-5", effort="low", prompt="p@1", max_tokens=2000)
    llm = make_llm(binding, rate_limiter=limiter)
    assert isinstance(llm, ChatAnthropic)
    assert (llm.model, llm.max_tokens, llm.rate_limiter) == ("claude-haiku-5-5", 2000, limiter)
    assert llm._get_request_payload([("user", "hi")])["output_config"] == {"effort": "low"}
