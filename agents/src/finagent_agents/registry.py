"""Load workflows.yaml and resolve every name (graph, node, prompt, tool) at load time."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from finagent_agents.graphs import GRAPHS
from finagent_agents.tools import TOOLS

PACKAGE_DIR = Path(__file__).parent
DEFAULT_WORKFLOWS_FILE = PACKAGE_DIR / "workflows.yaml"
DEFAULT_PROMPTS_DIR = PACKAGE_DIR / "prompts"

DEFAULTS = {"model": "claude-opus-5-5", "effort": "medium", "max_tokens": 16000,
            "timeout_s": 120, "max_concurrency": 4}
NODE_KEYS = {"model", "effort", "max_tokens", "prompt", "tools"}
WORKFLOW_KEYS = {"graph", "input", "nodes", "timeout_s", "max_concurrency", "schedule"}
INPUT_TYPES = {"str": str, "int": int, "float": float, "bool": bool, "list[str]": list[str]}


class WorkflowError(Exception):
    pass


class InputError(ValueError):
    pass


@dataclass(frozen=True)
class NodeBinding:
    model: str
    effort: str
    prompt: str  # name@version
    tools: tuple[str, ...] = ()
    max_tokens: int = 16000
    system: str = ""  # resolved prompt text

    def describe(self) -> dict:
        return {"model": self.model, "effort": self.effort, "prompt": self.prompt,
                "tools": list(self.tools)}


@dataclass(frozen=True)
class Workflow:
    name: str
    graph: str
    nodes: dict[str, NodeBinding]
    input_model: type[BaseModel]
    timeout_s: float
    max_concurrency: int
    schedule: str | None = None
    input: dict[str, str] = field(default_factory=dict)

    def validate(self, inputs: dict) -> dict:
        try:
            return self.input_model.model_validate(inputs).model_dump()
        except ValidationError as e:
            raise InputError(f"{self.name}: {e}") from e

    def describe(self) -> dict:
        return {node: b.describe() for node, b in self.nodes.items()}


def load_prompt(prompts_dir: Path, ref: str) -> str:
    name, sep, version = ref.partition("@")
    if not sep or not name or not version.isdigit():
        raise WorkflowError(f"prompt ref {ref!r} must be name@version")
    path = Path(prompts_dir) / f"{name}.v{version}.md"
    if not path.is_file():
        raise WorkflowError(f"prompt {ref!r} not found at {path}")
    return path.read_text(encoding="utf-8")


def load_workflows(
    path: Path = DEFAULT_WORKFLOWS_FILE, prompts_dir: Path = DEFAULT_PROMPTS_DIR
) -> dict[str, Workflow]:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    defaults = {**DEFAULTS, **(doc.get("defaults") or {})}
    return {
        name: _workflow(name, spec or {}, defaults, prompts_dir)
        for name, spec in (doc.get("workflows") or {}).items()
    }


def _workflow(name: str, spec: dict, defaults: dict, prompts_dir: Path) -> Workflow:
    def fail(msg: str):
        raise WorkflowError(f"workflow {name!r}: {msg}")

    if unknown := set(spec) - WORKFLOW_KEYS:
        fail(f"unknown keys {sorted(unknown)}")
    graph = spec.get("graph")
    if graph not in GRAPHS:
        fail(f"unknown graph {graph!r}")
    nodes_spec = spec.get("nodes") or {}
    expected = set(GRAPHS[graph].nodes)
    if set(nodes_spec) != expected:
        fail(f"nodes must be {sorted(expected)}, got {sorted(nodes_spec)}")

    nodes = {}
    for node, n in nodes_spec.items():
        n = n or {}
        if unknown := set(n) - NODE_KEYS:
            fail(f"node {node!r} has unknown keys {sorted(unknown)}")
        if "prompt" not in n:
            fail(f"node {node!r} needs a prompt")
        tools = tuple(n.get("tools") or ())
        if missing := [t for t in tools if t not in TOOLS]:
            fail(f"node {node!r} has unknown tool(s) {missing}")
        try:
            system = load_prompt(prompts_dir, n["prompt"])
        except WorkflowError as e:
            fail(str(e))
        nodes[node] = NodeBinding(
            model=n.get("model", defaults["model"]),
            effort=n.get("effort", defaults["effort"]),
            prompt=n["prompt"],
            tools=tools,
            max_tokens=n.get("max_tokens", defaults["max_tokens"]),
            system=system,
        )

    inputs = spec.get("input") or {}
    if bad := {k: t for k, t in inputs.items() if t not in INPUT_TYPES}:
        fail(f"unsupported input type(s) {bad}; use one of {sorted(INPUT_TYPES)}")
    input_model = create_model(
        f"{name}_input",
        __config__=ConfigDict(extra="forbid"),
        **{k: (INPUT_TYPES[t], ...) for k, t in inputs.items()},
    )

    return Workflow(
        name=name,
        graph=graph,
        nodes=nodes,
        input_model=input_model,
        timeout_s=spec.get("timeout_s", defaults["timeout_s"]),
        max_concurrency=spec.get("max_concurrency", defaults["max_concurrency"]),
        schedule=spec.get("schedule"),
        input=dict(inputs),
    )
