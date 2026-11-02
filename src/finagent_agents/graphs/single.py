"""One LLM call, no tools."""

from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from finagent_agents.context import GraphContext, format_inputs
from finagent_agents.graphs.agent import agent_graph, run_agent

NODES = ("agent",)


class State(TypedDict):
    inputs: dict
    result: str


def build(ctx: GraphContext, use_tools: bool = False) -> StateGraph:
    agent = agent_graph(ctx, "agent", use_tools=use_tools)

    async def run(state: State, config: RunnableConfig) -> dict:
        return {"result": await run_agent(agent, format_inputs(state["inputs"]), config)}

    graph = StateGraph(State)
    graph.add_node("agent", run)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)
    return graph
