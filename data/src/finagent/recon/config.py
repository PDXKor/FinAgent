from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINAGENT_", env_file=".env", extra="ignore")

    sec_user_agent: str  # SEC requires a contact email
    db_path: Path = Path("data/finagent.duckdb")
    raw_dir: Path = Path("data/raw")
    slice_file: Path = Path("data/slice.txt")
    schedule_timezone: str = "UTC"

    @field_validator("sec_user_agent")
    @classmethod
    def _needs_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("must include a contact email, e.g. 'FinAgent you@example.com'")
        return v
