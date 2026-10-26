"""CLI.

``finagent run``    one-shot; use this from an external scheduler (cron, systemd timer,
                    Kubernetes CronJob, ECS/Cloud Run jobs, GitHub Actions...).
``finagent serve``  long-running process with the built-in scheduler (Docker, VM, local).
"""

import argparse
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from finagent.config import get_settings
from finagent.runner import run_once

log = logging.getLogger("finagent")


def _job() -> None:
    try:
        log.info("report written to %s", run_once())
    except Exception:
        log.exception("scheduled run failed")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="finagent")
    parser.add_argument("command", choices=["run", "serve"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "run":
        print(run_once())
        return

    s = get_settings()
    sched = BlockingScheduler(timezone=s.schedule_timezone)
    sched.add_job(_job, CronTrigger.from_crontab(s.schedule_cron, timezone=s.schedule_timezone))
    log.info("scheduler started: %s (%s)", s.schedule_cron, s.schedule_timezone)
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
