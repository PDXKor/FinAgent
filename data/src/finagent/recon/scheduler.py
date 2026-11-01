import logging
from collections.abc import Callable
from pathlib import Path

import yaml
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from finagent.recon.jobs import REGISTRY

log = logging.getLogger(__name__)

DEFAULT_FILE = Path(__file__).with_name("jobs.yaml")
MISFIRE_GRACE_SECONDS = 3600  # run late (e.g. after laptop sleep) within the hour, else skip


class ScheduleError(Exception):
    pass


_DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]


def _weekday_names(field: str) -> str:
    """Standard cron numbers weekdays 0/7=Sun..6=Sat; APScheduler uses 0=Mon. Use names instead."""
    if field == "*" or any(c.isalpha() for c in field):
        return field
    days: set[int] = set()
    for part in field.split(","):
        span, slash, step = part.partition("/")
        stride = int(step) if slash else 1
        if span == "*":
            lo, hi = 0, 6
        elif "-" in span:
            lo, hi = (int(x) for x in span.split("-"))
        else:
            lo = int(span)
            hi = 6 if slash else lo
        days.update(d % 7 for d in range(lo, hi + 1, stride))
    return ",".join(_DAYS[d] for d in sorted(days))


def _trigger(cron: str, timezone: str = "UTC") -> CronTrigger:
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError(f"expected 5 fields, got {len(fields)}")
    minute, hour, day, month, weekday = fields
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=_weekday_names(weekday),
        timezone=timezone,
    )


def load_schedule(path: str | Path) -> dict[str, str]:
    """Read jobs.yaml into {job name: cron expression}, validating both."""
    path = Path(path)
    if not path.exists():
        raise ScheduleError(f"schedule file not found: {path}")
    doc = yaml.safe_load(path.read_text()) or {}
    schedule: dict[str, str] = {}
    for name, cfg in (doc.get("jobs") or {}).items():
        if name not in REGISTRY:
            raise ScheduleError(f"unknown job in schedule: {name}")
        cron = (cfg or {}).get("schedule")
        if not cron:
            raise ScheduleError(f"{name}: missing 'schedule'")
        try:
            _trigger(cron)
        except ValueError as e:
            raise ScheduleError(f"{name}: invalid cron {cron!r}: {e}") from e
        schedule[name] = cron
    return schedule


def _guarded(run: Callable[[str], object], name: str) -> None:
    log.info("starting %s", name)
    try:
        code = run(name)
    except Exception:  # a failed run must not stop the scheduler
        log.exception("scheduled job failed: %s", name)
        return
    if code not in (0, None):
        log.warning("%s finished with exit code %s", name, code)


def build_scheduler(
    schedule: dict[str, str], timezone: str, run: Callable[[str], object]
) -> BlockingScheduler:
    # One worker: jobs run serially, so DuckDB has a single writer and dependents wait for inputs.
    sched = BlockingScheduler(executors={"default": ThreadPoolExecutor(1)}, timezone=timezone)
    for name, cron in schedule.items():
        sched.add_job(
            _guarded,
            _trigger(cron, timezone),
            args=[run, name],
            id=name,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
        )
    return sched
