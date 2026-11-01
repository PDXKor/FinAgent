from datetime import date
from pathlib import Path

import pytest

from recon.jobs.base import Request
from recon.jobs.sec_frames import SecFrames, recent_frames

pytestmark = pytest.mark.unit

BODY = (Path(__file__).parent / "fixtures" / "frames_public_float.json").read_bytes()
REQ = Request("https://x/frame", "EntityPublicFloat_CY2025Q2I")


def test_recent_frames_are_the_latest_six_quarters_newest_first():
    assert recent_frames(date(2026, 11, 1)) == [
        "CY2026Q3I", "CY2026Q2I", "CY2026Q1I", "CY2025Q4I", "CY2025Q3I", "CY2025Q2I"
    ]  # fmt: skip


def test_recent_frames_include_a_quarter_only_once_it_has_ended():
    assert recent_frames(date(2026, 9, 30), 1) == ["CY2026Q3I"]
    assert recent_frames(date(2026, 9, 29), 1) == ["CY2026Q2I"]


def test_recent_frames_cross_year_boundary():
    assert recent_frames(date(2026, 1, 15), 2) == ["CY2025Q4I", "CY2025Q3I"]


def test_declares_name_source_and_keys():
    job = SecFrames()
    assert (job.name, job.source) == ("sec_frames", "sec")
    assert job.keys == {"public_float": ["cik", "period_end"]}


def test_plan_requests_one_optional_frame_per_quarter():
    reqs = list(SecFrames(today=date(2026, 11, 1)).plan(None))
    assert len(reqs) == 6
    first = reqs[0]
    assert (
        first.url == "https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/CY2026Q3I.json"
    )
    assert first.key == "EntityPublicFloat_CY2026Q3I"
    assert all(r.optional for r in reqs)


def test_parse_maps_frame_points_to_public_float_rows():
    rows = {r["cik"]: r for r in SecFrames().parse(REQ, BODY)["public_float"]}
    plug = rows["0001093691"]
    assert plug["period_end"] == date(2025, 6, 30)
    assert plug["value"] == 1_500_000_000
    assert plug["accession_no"] == "0001093691-26-000010"
    assert plug["location"] == "US-NY"
    assert rows["0000320193"]["period_end"] == date(2025, 3, 28)  # non-June fiscal year
    assert len(rows) == 3
