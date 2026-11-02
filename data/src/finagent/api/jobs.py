"""Runs recon jobs for the API: one at a time, each in a background thread.

Progress and results live in `ingest_runs` (written by the recon runner). This only tracks
which job is active and errors that stopped a job before or outside its run record.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from finagent.data.timeutil import utcnow

log = logging.getLogger(__name__)


class JobBusyError(Exception):
    pass


@dataclass(frozen=True)
class ActiveJob:
    job: str
    started_at: datetime  # naive UTC


class JobManager:
    def __init__(self, run: Callable[[str], object]):
        self._run = run
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._done.set()
        self.active: ActiveJob | None = None
        self.last_error: dict[str, str] = {}

    def start(self, job: str) -> ActiveJob:
        """Start `job` in a thread. Raises JobBusyError if any job is running: recon jobs
        share one writer and depend on each other, so they never overlap."""
        with self._lock:
            if self.active is not None:
                raise JobBusyError(f"{self.active.job} is already running")
            active = self.active = ActiveJob(job, utcnow())
            self.last_error.pop(job, None)
            self._done.clear()
        threading.Thread(target=self._work, args=(job,), name=f"recon-{job}", daemon=True).start()
        return active

    def wait(self, timeout: float | None = None) -> bool:
        """Block until no job is running. For tests and shutdown."""
        return self._done.wait(timeout)

    def _work(self, job: str) -> None:
        try:
            self._run(job)
        except Exception as e:  # report to the UI; never kill the server
            log.exception("job %s failed", job)
            self.last_error[job] = f"{type(e).__name__}: {e}"
        finally:
            with self._lock:
                self.active = None
                self._done.set()
