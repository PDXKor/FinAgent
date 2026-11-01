from datetime import UTC, datetime

import pytest

from recon.scheduler import ScheduleError, build_scheduler, load_schedule

pytestmark = pytest.mark.unit


def write(tmp_path, text):
    path = tmp_path / "jobs.yaml"
    path.write_text(text)
    return path


def test_load_schedule_maps_job_to_cron(tmp_path):
    path = write(
        tmp_path,
        'jobs:\n  sec_tickers: { schedule: "0 6 * * *" }\n  sec_submissions: { schedule: "0 7 * * 1-5" }\n',
    )
    assert load_schedule(path) == {"sec_tickers": "0 6 * * *", "sec_submissions": "0 7 * * 1-5"}


def test_load_schedule_rejects_unknown_job(tmp_path):
    path = write(tmp_path, 'jobs:\n  nope: { schedule: "0 6 * * *" }\n')
    with pytest.raises(ScheduleError, match="nope"):
        load_schedule(path)


def test_load_schedule_rejects_bad_cron(tmp_path):
    path = write(tmp_path, 'jobs:\n  sec_tickers: { schedule: "not a cron" }\n')
    with pytest.raises(ScheduleError, match="sec_tickers"):
        load_schedule(path)


def test_load_schedule_rejects_missing_schedule_key(tmp_path):
    path = write(tmp_path, "jobs:\n  sec_tickers: {}\n")
    with pytest.raises(ScheduleError, match="sec_tickers"):
        load_schedule(path)


def test_load_schedule_missing_file_raises(tmp_path):
    with pytest.raises(ScheduleError, match="jobs.yaml"):
        load_schedule(tmp_path / "jobs.yaml")


def next_fire(sched, name, after):
    return sched.get_job(name).trigger.get_next_fire_time(None, after)


def test_scheduler_fires_each_job_at_its_cron_time():
    sched = build_scheduler({"sec_tickers": "0 6 * * *"}, "UTC", run=lambda name: 0)
    after = datetime(2026, 10, 31, 7, 0, tzinfo=UTC)
    assert next_fire(sched, "sec_tickers", after) == datetime(2026, 11, 1, 6, 0, tzinfo=UTC)


def test_scheduler_honors_timezone():
    sched = build_scheduler({"sec_tickers": "0 6 * * *"}, "America/New_York", run=lambda n: 0)
    after = datetime(2027, 1, 15, 0, 0, tzinfo=UTC)
    assert next_fire(sched, "sec_tickers", after) == datetime(2027, 1, 15, 11, 0, tzinfo=UTC)


def test_scheduler_skips_weekends_for_weekday_cron():
    sched = build_scheduler({"sec_submissions": "0 7 * * 1-5"}, "UTC", run=lambda n: 0)
    friday_after = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)  # Fri
    assert next_fire(sched, "sec_submissions", friday_after) == datetime(
        2026, 11, 2, 7, 0, tzinfo=UTC
    )  # Mon


def test_scheduled_job_calls_run_with_its_name():
    ran = []
    sched = build_scheduler({"sec_tickers": "0 6 * * *"}, "UTC", run=ran.append)
    job = sched.get_job("sec_tickers")
    job.func(*job.args)
    assert ran == ["sec_tickers"]


def test_scheduled_job_swallows_errors_so_scheduler_survives(caplog):
    def boom(name):
        raise RuntimeError("db locked")

    sched = build_scheduler({"sec_tickers": "0 6 * * *"}, "UTC", run=boom)
    job = sched.get_job("sec_tickers")
    job.func(*job.args)  # must not raise
    assert "db locked" in caplog.text


def test_jobs_do_not_overlap_and_catch_up_after_sleep():
    sched = build_scheduler({"sec_tickers": "0 6 * * *"}, "UTC", run=lambda n: 0)
    job = sched.get_job("sec_tickers")
    assert (job.max_instances, job.coalesce, job.misfire_grace_time) == (1, True, 3600)


@pytest.mark.parametrize(
    ("cron", "after", "expected"),
    [
        (
            "0 7 * * 0",
            datetime(2026, 10, 31, 8, 0, tzinfo=UTC),
            datetime(2026, 11, 1, 7, tzinfo=UTC),
        ),
        (
            "0 7 * * 7",
            datetime(2026, 10, 31, 8, 0, tzinfo=UTC),
            datetime(2026, 11, 1, 7, tzinfo=UTC),
        ),
        (
            "0 7 * * 1,3",
            datetime(2026, 11, 2, 8, 0, tzinfo=UTC),
            datetime(2026, 11, 4, 7, tzinfo=UTC),
        ),
        (
            "0 7 * * 6",
            datetime(2026, 10, 30, 8, 0, tzinfo=UTC),
            datetime(2026, 10, 31, 7, tzinfo=UTC),
        ),
        (
            "0 7 * * mon-fri",
            datetime(2026, 10, 30, 8, 0, tzinfo=UTC),
            datetime(2026, 11, 2, 7, tzinfo=UTC),
        ),
        (
            "0 7 * * */2",
            datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
            datetime(2026, 11, 3, 7, tzinfo=UTC),
        ),
    ],
)
def test_weekdays_follow_standard_cron_numbering(cron, after, expected):
    sched = build_scheduler({"sec_tickers": cron}, "UTC", run=lambda n: 0)
    assert next_fire(sched, "sec_tickers", after) == expected


def test_nonzero_exit_from_run_is_logged_as_warning(caplog):
    import logging

    sched = build_scheduler({"sec_tickers": "0 6 * * *"}, "UTC", run=lambda n: 1)
    job = sched.get_job("sec_tickers")
    with caplog.at_level(logging.WARNING):
        job.func(*job.args)
    assert "sec_tickers" in caplog.text and "exit code 1" in caplog.text


def test_default_schedule_file_is_valid_and_covers_every_job():
    from recon.jobs import REGISTRY
    from recon.scheduler import DEFAULT_FILE

    assert set(load_schedule(DEFAULT_FILE)) == set(REGISTRY)
