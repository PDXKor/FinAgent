import argparse
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from recon.config import Settings
from recon.jobs import REGISTRY
from recon.pipeline import reparse_job, run_job
from recon.scheduler import DEFAULT_FILE, ScheduleError, build_scheduler, load_schedule
from recon.store.db import DatabaseLockedError, connect

COUNTED_TABLES = ["companies", "tickers", "filings", "facts"]
SCHEDULED_LOCK_WAIT = 300  # seconds a scheduled run waits for another process to free the DB


def _status(settings: Settings) -> int:
    try:
        con = connect(settings.db_path)
    except DatabaseLockedError as e:
        print(f"status: failed: {e}")
        return 1
    try:
        runs = con.execute(
            "SELECT job, status, started_at, requests, rows_written, errors FROM ingest_runs "
            "QUALIFY row_number() OVER (PARTITION BY job ORDER BY started_at DESC) = 1 "
            "ORDER BY job"
        ).fetchall()
        if runs:
            print(f"{'job':<26}{'status':<9}{'started (UTC)':<21}{'req':>5}{'rows':>8}{'err':>5}")
            for job, status, started, req, rows, err in runs:
                when = f"{started:%Y-%m-%d %H:%M:%S}"
                print(f"{job:<26}{status:<9}{when:<21}{req or 0:>5}{rows or 0:>8}{err or 0:>5}")
        else:
            print("No runs yet.")
        print()
        for table in COUNTED_TABLES:
            n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
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
