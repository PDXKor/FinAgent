"""Everything a graph builder needs, resolved per node. Builders touch nothing else."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from finagent_agents.data import DataLayer
from finagent_agents.tools import TOOLS

if TYPE_CHECKING:
    from finagent_agents.registry import NodeBinding, Workflow

MakeLLM = Callable[["NodeBinding"], BaseChatModel]


def format_inputs(inputs: dict) -> str:
    """Run inputs as `key: value` lines; they form the first user message."""
    return "\n".join(
        f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}" for k, v in inputs.items()
    )


class GraphContext:
    def __init__(self, workflow: "Workflow", data: DataLayer, make_llm: MakeLLM):
        self.workflow = workflow
        self.data = data
        self._make_llm = make_llm

    def binding(self, node: str) -> "NodeBinding":
        return self.workflow.nodes[node]

    def prompt(self, node: str) -> str:
        return self.binding(node).system

    def tools(self, node: str) -> list[BaseTool]:
        return [TOOLS[name](self.data) for name in self.binding(node).tools]

    def llm(self, node: str, tools: list[BaseTool] | None = None) -> BaseChatModel:
        """Chat model for `node`, bound to `tools` when given."""
        llm = self._make_llm(self.binding(node))
        return llm.bind_tools(tools) if tools else llm
