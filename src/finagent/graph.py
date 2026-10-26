"""The LangGraph workflow: fetch data for a watchlist, then have the LLM write a brief."""

from typing import TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from finagent.sources import DataSource

SYSTEM_PROMPT = (
    "You are a financial data analyst. Summarize the provided market data factually and "
    "concisely. Do not give investment advice and do not invent figures not present in the data."
)


class State(TypedDict, total=False):
    tickers: list[str]
    quotes: list[dict]
    errors: list[str]
    report: str


def build_graph(llm: BaseChatModel, source: DataSource):
    def fetch(state: State) -> State:
        quotes, errors = [], []
        for t in state["tickers"]:
            try:
                quotes.append(source.get_quote(t))
            except Exception as e:  # one bad ticker shouldn't sink the run
                errors.append(f"{t}: {e}")
        return {"quotes": quotes, "errors": errors}

    def summarize(state: State) -> State:
        if not state["quotes"]:
            return {"report": "No data retrieved.\n" + "\n".join(state.get("errors", []))}
        msg = llm.invoke(
            [SystemMessage(SYSTEM_PROMPT), HumanMessage(f"Market data:\n{state['quotes']}")]
        )
        report = msg.content if isinstance(msg.content, str) else str(msg.content)
        if state.get("errors"):
            report += "\n\nErrors:\n" + "\n".join(state["errors"])
        return {"report": report}

    g = StateGraph(State)
    g.add_node("fetch", fetch)
    g.add_node("summarize", summarize)
    g.add_edge(START, "fetch")
    g.add_edge("fetch", "summarize")
    g.add_edge("summarize", END)
    return g.compile()
