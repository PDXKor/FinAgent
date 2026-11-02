import json
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from finagent.data.db import upsert
from finagent.data.raw import save_raw
from finagent.data.timeutil import utcnow
from finagent.recon.jobs.base import Job, Request

MAX_ATTEMPTS = 3
DEFAULT_RATES = {"sec": 5.0}  # requests/sec per source; SEC allows 10
MIN_SNAPSHOT_SHARE = 0.5  # a replacing snapshot below this share of the table is refused


class FetchError(Exception):
    pass


class RateLimiter:
    """Enforces a minimum interval between calls."""

    def __init__(self, rate: float, clock=time.monotonic, sleep=time.sleep):
        self.interval = 1.0 / rate
        self.clock = clock
        self.sleep = sleep
        self._next = 0.0

    def acquire(self) -> None:
        now = self.clock()
        wait = self._next - now
        if wait > 0:
            self.sleep(wait)
            now = self.clock()
        self._next = max(now, self._next) + self.interval


@dataclass
class RunResult:
    run_id: str
    status: str  # ok | partial | failed
    requests: int
    rows_written: int
    errors: int


class Runner:
    def __init__(
        self, con, client: httpx.Client, raw_dir, rates=None, sleep=time.sleep, raw_keep: int = 0
    ):
        self.con = con
        self.client = client
        self.raw_dir = raw_dir
        self.raw_keep = raw_keep
        self.rates = {**DEFAULT_RATES, **(rates or {})}
        self.sleep = sleep  # backoff sleeper
        self._limiters: dict[str, RateLimiter] = {}

    def run(self, job: Job) -> RunResult:
        return self._execute(job.name, lambda: job.plan(self.con), lambda r: self._process(job, r))

    def reparse(self, job: Job) -> RunResult:
        """Rebuild tables from the newest saved raw response per key, without fetching."""
        return self._execute(
            f"{job.name}:reparse",
            lambda: self._raw_requests(job),
            lambda r: self._ingest(job, r, Path(r.url).read_bytes()),
        )

    def _execute(self, name: str, plan, handle) -> RunResult:
        run_id = uuid4().hex
        self.con.execute(
            "INSERT INTO ingest_runs (run_id, job, started_at, status) VALUES (?, ?, ?, 'running')",
            [run_id, name, utcnow()],
        )
        requests = rows = errors = 0
        sample = None
        try:
            for req in plan():
                requests += 1
                try:
                    rows += handle(req)
                except Exception as e:  # noqa: BLE001 - one bad request must not stop the run
                    errors += 1
                    sample = sample or f"{req.url}: {e}"
        except Exception as e:
            self._finish(run_id, "failed", requests, rows, errors + 1, f"{type(e).__name__}: {e}")
            raise
        status = "ok" if errors == 0 else "failed" if errors == requests else "partial"
        self._finish(run_id, status, requests, rows, errors, sample)
        return RunResult(run_id, status, requests, rows, errors)

    def _raw_requests(self, job: Job):
        """One request per saved key; `url` carries the raw file path."""
        root = Path(self.raw_dir) / job.source / job.name
        if not root.is_dir():
            return
        for key_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            files = sorted(key_dir.glob("*.json"))
            if files:
                yield Request(str(files[-1]), key_dir.name)

    def _process(self, job: Job, req: Request) -> int:
        resp = self._fetch(job.source, req)
        if resp.status_code == 404:  # optional request with no data
            return 0
        now = utcnow()
        path = save_raw(
            self.raw_dir, job.source, job.name, req.key, resp.content, now, keep=self.raw_keep
        )
        written = self._ingest(job, req, resp.content)
        upsert(
            self.con,
            "source_state",
            [
                {
                    "job": job.name,
                    "key": req.key,
                    "last_fetched_at": now,
                    "last_status": resp.status_code,
                    "raw_path": str(path),
                }
            ],
            ["job", "key"],
        )
        return written

    def _ingest(self, job: Job, req: Request, body: bytes) -> int:
        written = 0
        for table, rows in job.parse(req, body).items():
            written += upsert(self.con, table, rows, job.keys[table])
            if table in getattr(job, "replace", ()):
                self._prune(table, job.keys[table], rows)
        return written

    def _prune(self, table: str, keys: list[str], rows: list[dict]) -> None:
        """Delete rows missing from a full snapshot. A suspiciously small snapshot (e.g. a
        truncated response) is refused rather than wiping the table."""
        (key,) = keys
        existing = self.con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if len(rows) < existing * MIN_SNAPSHOT_SHARE:
            raise ValueError(
                f"{table}: snapshot of {len(rows)} rows is under half of {existing}; not pruning"
            )
        self.con.execute(
            f"DELETE FROM {table} WHERE {key} NOT IN (SELECT value FROM json_each(?))",
            [json.dumps([r[key] for r in rows])],
        )

    def _fetch(self, source: str, req: Request) -> httpx.Response:
        limiter = self._limiters.setdefault(source, RateLimiter(self.rates.get(source, 1.0)))
        last = "no attempts"
        for attempt in range(MAX_ATTEMPTS):
            limiter.acquire()
            try:
                resp = self.client.get(req.url)
            except httpx.TransportError as e:
                last = f"{type(e).__name__}: {e}"
            else:
                if resp.status_code == 404 and req.optional:
                    return resp
                if resp.status_code != 429 and resp.status_code < 500:
                    resp.raise_for_status()  # non-retryable 4xx
                    return resp
                last = f"HTTP {resp.status_code}"
            if attempt < MAX_ATTEMPTS - 1:
                self.sleep(2**attempt)
        raise FetchError(f"{last} after {MAX_ATTEMPTS} attempts")

    def _finish(self, run_id, status, requests, rows, errors, sample) -> None:
        self.con.execute(
            "UPDATE ingest_runs SET finished_at = ?, status = ?, requests = ?, rows_written = ?, "
            "errors = ?, error_sample = ? WHERE run_id = ?",
            [utcnow(), status, requests, rows, errors, sample and sample[:500], run_id],
        )
