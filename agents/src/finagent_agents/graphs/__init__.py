from collections.abc import Callable
from dataclasses import dataclass

from langgraph.graph import StateGraph

from finagent_agents.context import GraphContext
from finagent_agents.graphs import react, single
from finagent_agents.graphs.multi import screen_then_brief


@dataclass(frozen=True)
class GraphSpec:
    nodes: tuple[str, ...]  # node names a workflow must bind (model, prompt, tools)
    build: Callable[[GraphContext], StateGraph]


# name -> spec. Graphs hold no config literals; workflows.yaml binds them.
GRAPHS = {
    "single": GraphSpec(single.NODES, single.build),
    "react": GraphSpec(react.NODES, react.build),
    "screen_then_brief": GraphSpec(screen_then_brief.NODES, screen_then_brief.build),
}
