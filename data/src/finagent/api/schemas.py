"""Wire contract, version /v1. Change by adding fields; anything breaking needs /v2."""

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel


def _as_utc(v: datetime) -> datetime:
    """The store keeps naive UTC; send it with an explicit offset so clients don't read
    it as local time."""
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class Company(BaseModel):
    ticker: str
    cik: str
    exchange: str | None = None
    name: str | None = None
    sic: str | None = None
    sic_desc: str | None = None
    state_inc: str | None = None
    fiscal_year_end: str | None = None


class AnnualFinancials(BaseModel):
    fiscal_year: int | None
    period_end: date
    revenue: float | None = None
    net_income: float | None = None
    operating_income: float | None = None
    assets: float | None = None
    liabilities: float | None = None
    equity: float | None = None
    cash: float | None = None
    shares_outstanding: float | None = None
    form: str | None = None
    filed_date: date | None = None


class AgentRunIn(BaseModel):
    workflow: str
    status: Literal["running", "ok", "failed", "timeout", "cancelled"]
    inputs: dict = {}
    output: Any = None
    error: str | None = None
    bindings: dict = {}
    started_at: UtcDatetime
    finished_at: UtcDatetime | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


class AgentRun(AgentRunIn):
    run_id: str


class AgentRunPage(BaseModel):
    items: list[AgentRun]
    next: UtcDatetime | None = None  # pass as `before` for the next page; null = last page


class IngestRun(BaseModel):
    run_id: str
    job: str
    status: str  # running | ok | partial | failed
    started_at: UtcDatetime
    finished_at: UtcDatetime | None = None
    requests: int | None = None
    rows_written: int | None = None
    errors: int | None = None
    error_sample: str | None = None


class Job(BaseModel):
    name: str
    schedule: str | None = None  # cron from jobs.yaml; the API does not run the scheduler
    running: bool = False  # started by this API process and not finished
    last_run: IngestRun | None = None
    last_error: str | None = None  # error that stopped the job outside its run record


class JobStarted(BaseModel):
    job: str
    started_at: UtcDatetime
