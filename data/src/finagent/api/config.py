from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINAGENT_", env_file=".env", extra="ignore")

    db_path: Path = Path("data/finagent.db")
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    api_token: str | None = None  # when set, requests need `Authorization: Bearer <token>`
    # Host header values accepted (blocks DNS rebinding). Add the service name in containers.
    api_allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    api_lock_wait: float = 5.0  # seconds a write waits for another writer before 503
    job_lock_wait: float = 30.0  # seconds an API-started recon job waits for the writer lock

    @field_validator("api_token")
    @classmethod
    def _blank_is_unset(cls, v: str | None) -> str | None:
        """Compose passes unset variables as empty strings; treat those as no token."""
        return v or None
