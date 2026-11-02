"""One agent that loops with its tools until it answers."""

from langgraph.graph import StateGraph

from finagent_agents.context import GraphContext
from finagent_agents.graphs import single

NODES = single.NODES


def build(ctx: GraphContext) -> StateGraph:
    return single.build(ctx, use_tools=True)
