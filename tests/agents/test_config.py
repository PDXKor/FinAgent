import pytest

from finagent_agents.config import AgentSettings
from finagent_agents.registry import DEFAULT_WORKFLOWS_FILE

pytestmark = pytest.mark.unit


def test_defaults_and_env_override(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert AgentSettings().workflows_file == DEFAULT_WORKFLOWS_FILE
    monkeypatch.setenv("FINAGENT_AGENTS_MAX_RUNS", "7")
    assert AgentSettings().max_runs == 7
