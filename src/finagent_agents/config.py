from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from finagent_agents.registry import DEFAULT_PROMPTS_DIR, DEFAULT_WORKFLOWS_FILE


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINAGENT_AGENTS_", env_file=".env", extra="ignore"
    )

    workflows_file: Path = DEFAULT_WORKFLOWS_FILE
    prompts_dir: Path = DEFAULT_PROMPTS_DIR
    max_runs: int = 4  # concurrent runs, all workflows
    requests_per_second: float = 5.0  # Claude request rate limit
    data_url: str | None = None  # FinAgentData API, e.g. http://127.0.0.1:8765; unset = memory
    data_token: str | None = None
