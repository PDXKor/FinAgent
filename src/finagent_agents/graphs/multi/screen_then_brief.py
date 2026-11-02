"""Two agents. A screener runs once per ticker (parallel fan-out), then a writer turns all
the screening notes into one brief. The writer has no financials tool, so it depends on the
screener's work."""

import operator
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from finagent_agents.context import GraphContext, format_inputs
from finagent_agents.graphs.agent import agent_graph, run_agent

NODES = ("screener", "writer")


class State(TypedDict):
    inputs: dict
    notes: Annotated[list[dict], operator.add]  # one {ticker, note} per screened ticker
    result: str


class ScreenInput(TypedDict):
    ticker: str


def build(ctx: GraphContext) -> StateGraph:
    screener = agent_graph(ctx, "screener")
    writer = agent_graph(ctx, "writer")

    def tickers_of(state: State) -> list[str]:
        tickers = list(dict.fromkeys(state["inputs"]["tickers"]))  # dedupe, keep order
        if not tickers:
            raise ValueError("tickers is empty")
        return tickers

    def fan_out(state: State) -> list[Send]:
        return [Send("screen", {"ticker": t}) for t in tickers_of(state)]

    async def screen(state: ScreenInput, config: RunnableConfig) -> dict:
        note = await run_agent(screener, format_inputs({"ticker": state["ticker"]}), config)
        return {"notes": [{"ticker": state["ticker"], "note": note}]}

    async def write(state: State, config: RunnableConfig) -> dict:
        notes = {n["ticker"]: n["note"] for n in state["notes"]}
        tickers = tickers_of(state)
        text = format_inputs({"tickers": tickers}) + "\n\nScreening notes:\n\n"
        text += "\n\n".join(f"## {t}\n{notes[t]}" for t in tickers)
        return {"result": await run_agent(writer, text, config)}

    graph = StateGraph(State)
    graph.add_node("screen", screen)
    graph.add_node("write", write)
    graph.add_conditional_edges(START, fan_out, ["screen"])
    graph.add_edge("screen", "write")
    graph.add_edge("write", END)
    return graph
