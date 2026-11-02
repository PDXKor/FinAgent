import asyncio
from collections.abc import Callable

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from finagent_agents.data import MemoryDataLayer

COMPANIES = {
    "AAPL": {"ticker": "AAPL", "cik": "0000320193", "name": "Apple Inc.", "sic_desc": "Computers"},
    "TSLA": {"ticker": "TSLA", "cik": "0001318605", "name": "Tesla, Inc.", "sic_desc": "Autos"},
}
FINANCIALS = {
    "AAPL": [{"period_end": "2025-06-30", "form": "10-Q", "revenue": 94.0e9}],
    "TSLA": [{"period_end": "2025-06-30", "form": "10-Q", "revenue": 22.5e9}],
}


class ScriptedChatModel(BaseChatModel):
    """Fake chat model: `respond(messages) -> AIMessage`, optional async delay.

    Tracks peak concurrent calls so tests can check runner limits.
    """

    respond: Callable[[list[BaseMessage]], AIMessage]
    delay: float = 0.0
    in_flight: int = 0
    peak: int = 0
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=self.respond(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return self._generate(messages)
        finally:
            self.in_flight -= 1


def ai(text: str, tokens: tuple[int, int] = (10, 5)) -> AIMessage:
    i, o = tokens
    return AIMessage(
        content=text,
        usage_metadata={"input_tokens": i, "output_tokens": o, "total_tokens": i + o},
    )


def call(name: str, args: dict, id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id}])


def first_human(messages: list[BaseMessage]) -> str:
    return next(m.content for m in messages if isinstance(m, HumanMessage))


def tool_results(messages: list[BaseMessage]) -> list[ToolMessage]:
    return [m for m in messages if isinstance(m, ToolMessage)]


@pytest.fixture
def data():
    return MemoryDataLayer(companies=COMPANIES, financials=FINANCIALS)


@pytest.fixture
def scripted():
    def make(respond, delay=0.0):
        return ScriptedChatModel(respond=respond, delay=delay)

    return make
