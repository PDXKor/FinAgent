"""Seam to the storage repo (FinAgentData).

Agents depend only on `DataLayer`. `HttpDataLayer` talks to the FinAgentData API;
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


@dataclass
class RunRecord:
    run_id: str
    workflow: str
    inputs: dict
    status: str  # running | ok | failed | timeout
    started_at: datetime
    finished_at: datetime | None = None
    output: Any = None
    error: str | None = None
    bindings: dict = field(default_factory=dict)  # node -> {model, effort, prompt, tools}
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


class DataLayer(Protocol):
    async def get_company(self, ticker: str) -> dict | None: ...

    async def get_financials(self, ticker: str, limit: int = 8) -> list[dict]:
        """Most recent reported periods first."""
        ...

    async def save_run(self, run: RunRecord) -> None:
        """Insert or replace by run_id."""
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
