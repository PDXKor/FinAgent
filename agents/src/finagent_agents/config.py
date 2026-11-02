from pathlib import Path

from pydantic import field_validator
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
    api_host: str = "127.0.0.1"  # `serve`
    api_port: int = 8766
    api_token: str | None = None  # when set, requests need `Authorization: Bearer <token>`
    # Host header values accepted (blocks DNS rebinding). Add the service name in containers.
    api_allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    event_retention: int = 100  # finished runs whose live events stay replayable

    @field_validator("data_url", "data_token", "api_token")
    @classmethod
    def _blank_is_unset(cls, v: str | None) -> str | None:
        """Compose passes unset variables as empty strings."""
        return v or None
