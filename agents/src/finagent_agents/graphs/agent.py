"""One LLM agent as a compiled graph: agent <-> ToolNode loop. Shared by every workflow graph."""

from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from finagent_agents.context import GraphContext


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def text_of(message: AnyMessage) -> str:
    """Plain text of a reply; Claude may return content blocks (thinking, text)."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        b if isinstance(b, str) else b.get("text", "") for b in content if isinstance(b, (str, dict))
    )


def agent_graph(ctx: GraphContext, node: str, use_tools: bool = True) -> CompiledStateGraph:
    """Agent for workflow node `node`: its model, static system prompt and tools."""
    tools = ctx.tools(node) if use_tools else []
    llm = ctx.llm(node, tools)
    # Static system prompt, marked cacheable. Run inputs go in the user message.
    system = SystemMessage(
        content=[{"type": "text", "text": ctx.prompt(node), "cache_control": {"type": "ephemeral"}}]
    )

    async def call_model(state: AgentState, config: RunnableConfig) -> dict:
        return {"messages": [await llm.ainvoke([system, *state["messages"]], config)]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_edge(START, "agent")
    if tools:
        graph.add_node("tools", ToolNode(tools))
        graph.add_conditional_edges("agent", tools_condition)
        graph.add_edge("tools", "agent")
    else:
        graph.add_edge("agent", END)
    return graph.compile()


async def run_agent(agent: CompiledStateGraph, text: str, config: RunnableConfig) -> str:
    """Run `agent` on one user message; return its final text."""
    out = await agent.ainvoke({"messages": [HumanMessage(text)]}, config)
    last = out["messages"][-1]
    assert isinstance(last, AIMessage)
    return text_of(last)
