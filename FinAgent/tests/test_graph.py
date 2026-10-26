from langchain_core.language_models.fake_chat_models import FakeListChatModel

from finagent.graph import build_graph
from finagent.llm import get_llm, register_provider
from finagent.config import Settings


class FakeSource:
    def get_quote(self, ticker):
        if ticker == "BAD":
            raise RuntimeError("not found")
        return {"ticker": ticker, "price": 10.0}


def test_graph_produces_report_and_tolerates_bad_ticker():
    graph = build_graph(FakeListChatModel(responses=["summary"]), FakeSource())
    out = graph.invoke({"tickers": ["AAPL", "BAD"]})
    assert out["report"].startswith("summary")
    assert "BAD: not found" in out["report"]


def test_llm_factory_custom_provider_and_unknown():
    register_provider("fake", lambda s: FakeListChatModel(responses=["x"]))
    assert get_llm(Settings(llm_provider="fake")) is not None
    try:
        get_llm(Settings(llm_provider="nope"))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
