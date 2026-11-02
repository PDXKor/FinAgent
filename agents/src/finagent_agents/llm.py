from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import BaseRateLimiter

from finagent_agents.registry import NodeBinding

MAX_RETRIES = 3  # SDK retries 429/5xx/connection errors with backoff


def make_llm(binding: NodeBinding, rate_limiter: BaseRateLimiter | None = None) -> BaseChatModel:
    """Claude chat model for one node. Key comes from ANTHROPIC_API_KEY.

    Opus 5.5: thinking is always on; `effort` is the depth control. Forced tool_choice
    is rejected, so graphs bind tools with the default (auto).
    """
    return ChatAnthropic(
        model=binding.model,
        reasoning_effort=binding.effort,
        max_tokens=binding.max_tokens,
        max_retries=MAX_RETRIES,
        rate_limiter=rate_limiter,
    )
