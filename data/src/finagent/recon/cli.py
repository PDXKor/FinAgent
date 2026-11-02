import argparse
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from finagent.data.db import DatabaseLockedError, connect
from finagent.data.queries.ops import latest_ingest_runs, table_counts
from finagent.recon.config import Settings
from finagent.recon.jobs import REGISTRY
from finagent.recon.pipeline import reparse_job, run_job
from finagent.recon.scheduler import DEFAULT_FILE, ScheduleError, build_scheduler, load_schedule

COUNTED_TABLES = ["companies", "tickers", "filings", "facts"]
SCHEDULED_LOCK_WAIT = 300  # seconds a scheduled run waits for another process to free the DB


def _status(settings: Settings) -> int:
    try:
        con = connect(settings.db_path)
    except DatabaseLockedError as e:
        print(f"status: failed: {e}")
        return 1
    try:
        runs = latest_ingest_runs(con)
        if runs:
            print(f"{'job':<26}{'status':<9}{'started (UTC)':<21}{'req':>5}{'rows':>8}{'err':>5}")
            for r in runs:
                job, status, req, rows, err = (
                    r["job"], r["status"], r["requests"], r["rows_written"], r["errors"]
                )  # fmt: skip
                when = r["started_at"][:19]  # ISO text: YYYY-MM-DD HH:MM:SS
                print(f"{job:<26}{status:<9}{when:<21}{req or 0:>5}{rows or 0:>8}{err or 0:>5}")
        else:
            print("No runs yet.")
        print()
        for table, n in table_counts(con, COUNTED_TABLES).items():
            print(f"{table:<12}{n:>10}")
    finally:
        con.close()
    return 0


def _schedule(settings: Settings, file: str, list_only: bool) -> int:
    try:
        schedule = load_schedule(file)
    except ScheduleError as e:
        print(f"schedule: failed: {e}")
        return 1
    tz = settings.schedule_timezone
    sched = build_scheduler(
        schedule, tz, run=lambda name: run_job(settings, name, lock_wait=SCHEDULED_LOCK_WAIT)
    )
    if list_only:
        now = datetime.now(ZoneInfo(tz))
        print(f"{'job':<26}{'cron':<16}next run ({tz})")
        for job in sched.get_jobs():
            nxt = job.trigger.get_next_fire_time(None, now)
            print(f"{job.id:<20}{schedule[job.id]:<16}{nxt:%Y-%m-%d %H:%M}")
        return 0
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(f"Scheduling {len(schedule)} jobs ({tz}). Ctrl+C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


def main(argv: list[str] | None = None, client: httpx.Client | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recon")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run one ingestion job now")
    run.add_argument("job", choices=sorted(REGISTRY))
    reparse = sub.add_parser("reparse", help="rebuild a job's tables from saved raw responses")
    reparse.add_argument("job", choices=sorted(REGISTRY))
    sched = sub.add_parser("schedule", help="run jobs on their cron schedule (blocks)")
    sched.add_argument("--file", default=str(DEFAULT_FILE), help="schedule file (jobs.yaml)")
    sched.add_argument("--list", action="store_true", help="show schedule and next runs, then exit")
    sub.add_parser("status", help="last run per job and table row counts")
    args = parser.parse_args(argv)

    settings = Settings()
    if args.cmd == "run":
        return run_job(settings, args.job, client)
    if args.cmd == "reparse":
        return reparse_job(settings, args.job)
    if args.cmd == "schedule":
        return _schedule(settings, args.file, args.list)
    return _status(settings)


if __name__ == "__main__":
    raise SystemExit(main())
