from pathlib import Path

import pytest
from pydantic import ValidationError

from finagent.recon.config import Settings

pytestmark = pytest.mark.unit


def test_reads_finagent_prefixed_env(monkeypatch):
    monkeypatch.setenv("FINAGENT_SEC_USER_AGENT", "FinAgent me@corp.com")
    monkeypatch.setenv("FINAGENT_DB_PATH", "x/y.duckdb")
    s = Settings(_env_file=None)
    assert s.sec_user_agent == "FinAgent me@corp.com"
    assert s.db_path == Path("x/y.duckdb")
    assert s.raw_dir == Path("data/raw")


def test_user_agent_is_required(monkeypatch):
    monkeypatch.delenv("FINAGENT_SEC_USER_AGENT", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_user_agent_must_contain_contact_email(monkeypatch):
    monkeypatch.setenv("FINAGENT_SEC_USER_AGENT", "FinAgent")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_schedule_timezone_defaults_to_utc_and_is_overridable(monkeypatch):
    monkeypatch.setenv("FINAGENT_SEC_USER_AGENT", "FinAgent me@corp.com")
    assert Settings(_env_file=None).schedule_timezone == "UTC"
    monkeypatch.setenv("FINAGENT_SCHEDULE_TIMEZONE", "America/New_York")
    assert Settings(_env_file=None).schedule_timezone == "America/New_York"
