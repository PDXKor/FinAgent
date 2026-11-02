"""Seam to the data package (`data/` in this monorepo), reached only over its HTTP API.

Agents depend only on `DataLayer`. `HttpDataLayer` talks to the data API;
`MemoryDataLayer` serves tests and local runs. Async so a backend never blocks the event loop.
Add methods only when a tool needs them.
"""

import asyncio
import copy
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Protocol, Self
from urllib.parse import quote

import httpx

BUSY_RETRIES = 3  # retries when the API answers 503 (database busy)
BUSY_BACKOFF_S = 0.5  # doubled per retry
CONNECT_RETRIES = 2
MAX_PAGE = 200  # data API cap on list endpoints


@dataclass
class RunRecord:
    run_id: str
    workflow: str
    inputs: dict
    status: str  # running | ok | failed | timeout | cancelled
    started_at: datetime
    finished_at: datetime | None = None
    output: Any = None
    error: str | None = None
    bindings: dict = field(default_factory=dict)  # node -> {model, effort, prompt, tools}
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "RunRecord":
        """From the API's JSON (ISO timestamps)."""
        fields = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        for k in ("started_at", "finished_at"):
            if isinstance(fields.get(k), str):
                fields[k] = datetime.fromisoformat(fields[k])
        return cls(**fields)


class DataLayer(Protocol):
    async def get_company(self, ticker: str) -> dict | None: ...

    async def get_financials(self, ticker: str, limit: int = 8) -> list[dict]:
        """Most recent reported periods first."""
        ...

    async def save_run(self, run: RunRecord) -> None:
        """Insert or replace by run_id."""
        ...

    async def list_runs(self, status: str | None = None, limit: int = 200) -> list[RunRecord]:
        """Newest first."""
        ...


class MemoryDataLayer:
    def __init__(self, companies: dict | None = None, financials: dict | None = None):
        self.companies = companies or {}
        self.financials = financials or {}
        self.runs: dict[str, RunRecord] = {}

    async def get_company(self, ticker: str) -> dict | None:
        company = self.companies.get(ticker)
        return copy.deepcopy(company) if company else None

    async def get_financials(self, ticker: str, limit: int = 8) -> list[dict]:
        return copy.deepcopy(self.financials.get(ticker, [])[:limit])

    async def save_run(self, run: RunRecord) -> None:
        self.runs[run.run_id] = copy.deepcopy(run)

    async def list_runs(self, status: str | None = None, limit: int = 200) -> list[RunRecord]:
        runs = sorted(self.runs.values(), key=lambda r: r.started_at, reverse=True)
        return [copy.deepcopy(r) for r in runs if status in (None, r.status)][:limit]


def _json_default(v: Any) -> str:
    """Datetimes as ISO text; any other non-JSON value (e.g. an odd output) as its str()."""
    return v.isoformat() if isinstance(v, datetime) else str(v)


class HttpDataLayer:
    """Client for the FinAgentData HTTP API (/v1). Use within one event loop; close with
    `aclose` or `async with`."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/v1",
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=timeout,
            transport=transport or httpx.AsyncHTTPTransport(retries=CONNECT_RETRIES),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        for attempt in range(BUSY_RETRIES + 1):
            r = await self._client.request(method, path, **kwargs)
            if r.status_code != 503 or attempt == BUSY_RETRIES:
                return r
            await asyncio.sleep(BUSY_BACKOFF_S * 2**attempt)
        raise AssertionError("unreachable")

    async def get_company(self, ticker: str) -> dict | None:
        r = await self._request("GET", f"/companies/{quote(ticker, safe='')}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def get_financials(self, ticker: str, limit: int = 8) -> list[dict]:
        r = await self._request(
            "GET", f"/companies/{quote(ticker, safe='')}/financials", params={"limit": limit}
        )
        r.raise_for_status()
        return r.json()

    async def save_run(self, run: RunRecord) -> None:
        body = asdict(run)
        run_id = body.pop("run_id")
        body = json.loads(json.dumps(body, default=_json_default))
        r = await self._request("PUT", f"/agent-runs/{quote(run_id, safe='')}", json=body)
        r.raise_for_status()

    async def list_runs(self, status: str | None = None, limit: int = 200) -> list[RunRecord]:
        runs: list[RunRecord] = []
        before = None
        while len(runs) < limit:
            params = {"limit": min(MAX_PAGE, limit - len(runs))}
            params |= {k: v for k, v in (("status", status), ("before", before)) if v}
            r = await self._request("GET", "/agent-runs", params=params)
            r.raise_for_status()
            page = r.json()
            runs += [RunRecord.from_dict(d) for d in page["items"]]
            if not (before := page["next"]):
                break
        return runs
