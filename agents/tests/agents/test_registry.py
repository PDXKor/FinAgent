import pytest

from finagent_agents.registry import (
    DEFAULT_PROMPTS_DIR,
    DEFAULT_WORKFLOWS_FILE,
    InputError,
    WorkflowError,
    load_prompt,
    load_workflows,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def write(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "p.v1.md").write_text("You are a test.\n")

    def make(body: str):
        path = tmp_path / "workflows.yaml"
        path.write_text(body)
        return load_workflows(path, prompts_dir=tmp_path / "prompts")

    return make


def test_repo_workflows_load():
    wfs = load_workflows(DEFAULT_WORKFLOWS_FILE, prompts_dir=DEFAULT_PROMPTS_DIR)
    assert {"ping", "company_brief", "screen_then_brief"} <= set(wfs)
    node = wfs["company_brief"].nodes["agent"]
    assert node.model == "claude-opus-5-5"
    assert node.tools == ("get_company", "get_financials")
    assert node.system.strip()


def test_defaults_and_overrides(write):
    wfs = write(
        """
defaults: { model: m-default, effort: medium, timeout_s: 30, max_concurrency: 2 }
workflows:
  w:
    graph: single
    input: { text: str }
    timeout_s: 5
    nodes:
      agent: { prompt: p@1, model: m-node, effort: low }
"""
    )
    w = wfs["w"]
    assert (w.timeout_s, w.max_concurrency) == (5, 2)
    assert (w.nodes["agent"].model, w.nodes["agent"].effort) == ("m-node", "low")
    assert w.nodes["agent"].system == "You are a test.\n"


@pytest.mark.parametrize(
    "body, message",
    [
        ("graph: nope\n    nodes: { agent: { prompt: p@1 } }", "unknown graph"),
        ("graph: single\n    nodes: { other: { prompt: p@1 } }", "nodes"),
        ("graph: single\n    nodes: { agent: { prompt: p@9 } }", "prompt"),
        ("graph: react\n    nodes: { agent: { prompt: p@1, tools: [nope] } }", "unknown tool"),
        ("graph: single\n    input: { x: dict }\n    nodes: { agent: { prompt: p@1 } }", "type"),
        ("graph: single\n    nodes: { agent: { prompt: p@1, colour: red } }", "colour"),
    ],
)
def test_invalid_workflow_raises_at_load(write, body, message):
    with pytest.raises(WorkflowError, match=message):
        write(f"workflows:\n  w:\n    {body}\n")


def test_validate_inputs(write):
    w = write(
        'workflows:\n  w:\n    graph: single\n    input: { tickers: "list[str]", n: int }\n'
        "    nodes: { agent: { prompt: p@1 } }\n"
    )["w"]
    assert w.validate({"tickers": ["A"], "n": "3"}) == {"tickers": ["A"], "n": 3}
    with pytest.raises(InputError, match="tickers"):
        w.validate({"n": 3})
    with pytest.raises(InputError, match="extra"):
        w.validate({"tickers": [], "n": 1, "extra": 1})


def test_load_prompt_by_ref(tmp_path):
    (tmp_path / "brief.v2.md").write_text("v2 text")
    assert load_prompt(tmp_path, "brief@2") == "v2 text"
    with pytest.raises(WorkflowError, match="name@version"):
        load_prompt(tmp_path, "brief")
