"""Runtime configuration, read from environment variables (prefix FINAGENT_) or a .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINAGENT_", env_file=".env", extra="ignore")

    # LLM layer: provider is one of "anthropic", "openai", "ollama".
    llm_provider: str = "ollama"
    llm_model: str = "llama3.1"
    llm_temperature: float = 0.0
    llm_base_url: str | None = None  # e.g. Ollama host or an OpenAI-compatible endpoint

    # Data source name registered in finagent.sources.
    data_source: str = "yfinance"

    # Watchlist and schedule.
    tickers: list[str] = ["AAPL", "MSFT"]
    schedule_cron: str = "0 22 * * 1-5"  # weekdays 22:00 (UTC)
    schedule_timezone: str = "UTC"

    # Where reports are written (local dir; mount a volume or swap the sink for object storage).
    output_dir: str = "./reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
