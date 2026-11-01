from datetime import date, datetime
from pathlib import Path

import pytest

from finagent.data.db import upsert
from finagent.recon.jobs.base import Request
from finagent.recon.jobs.sec_companyfacts import SecCompanyFacts

pytestmark = pytest.mark.component

BODY = (Path(__file__).parent / "fixtures" / "companyfacts_0000320193.json").read_bytes()
AAPL = "0000320193"
REQ = Request(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{AAPL}.json", AAPL)


def facts():
    return SecCompanyFacts("unused").parse(REQ, BODY)["facts"]


def test_declares_name_source_and_keys():
    job = SecCompanyFacts("unused")
    assert (job.name, job.source) == ("sec_companyfacts", "sec")
    assert job.keys["facts"] == [
        "cik",
        "taxonomy",
        "concept",
        "unit",
        "period_start",
        "period_end",
        "accession_no",
    ]


def test_parse_keeps_only_tracked_concepts():
    assert {f["concept"] for f in facts()} == {
        "EntityCommonStockSharesOutstanding",
        "Assets",
        "NetIncomeLoss",
    }


def test_parse_maps_fields():
    assets = next(f for f in facts() if f["concept"] == "Assets")
    assert assets["cik"] == AAPL
    assert (assets["taxonomy"], assets["unit"], assets["value"]) == ("us-gaap", "USD", 364980000000)
    assert (assets["fy"], assets["fp"], assets["form"]) == (2024, "FY", "10-K")
    assert assets["accession_no"] == "0000320193-24-000123"
    assert assets["filed_date"] == date(2024, 11, 1)


def test_instant_facts_use_period_end_as_period_start():
    assets = next(f for f in facts() if f["concept"] == "Assets")
    assert assets["period_start"] == assets["period_end"] == date(2024, 9, 28)


def test_three_and_nine_month_facts_for_same_end_date_both_persist(con):
    rows = facts()
    job = SecCompanyFacts("unused")
    n = upsert(con, "facts", rows, job.keys["facts"])
    assert n == 5
    q3 = con.execute(
        "SELECT count(*) FROM facts WHERE accession_no = '0000320193-24-000100'"
    ).fetchone()[0]
    assert q3 == 2


def seed_filing(con, cik, form, filed):
    upsert(
        con,
        "filings",
        [{"accession_no": f"{cik}-{form}-{filed}", "cik": cik, "form": form, "filed_date": filed}],
        ["accession_no"],
    )


def fetched(con, cik, at):
    upsert(
        con,
        "source_state",
        [{"job": "sec_companyfacts", "key": cik, "last_fetched_at": at}],
        ["job", "key"],
    )


def planned(job, con):
    return [r.key for r in job.plan(con)]


def test_plan_fetches_never_fetched_ciks(con, slice_file):
    job = SecCompanyFacts(slice_file("AAPL", "TSLA"))
    assert planned(job, con) == ["0000320193", "0001318605"]
    assert next(iter(job.plan(con))).url == (
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    )


def test_plan_skips_cik_with_no_filing_since_last_fetch(con, slice_file):
    fetched(con, "0000320193", datetime(2024, 11, 5, 12))
    seed_filing(con, "0000320193", "10-K", date(2024, 11, 1))
    assert planned(SecCompanyFacts(slice_file("AAPL")), con) == []


def test_plan_refetches_when_new_annual_or_quarterly_filing(con, slice_file):
    fetched(con, "0000320193", datetime(2024, 11, 5, 12))
    seed_filing(con, "0000320193", "10-Q", date(2024, 11, 6))
    assert planned(SecCompanyFacts(slice_file("AAPL")), con) == ["0000320193"]


def test_plan_refetches_on_filing_the_same_day_as_last_fetch(con, slice_file):
    fetched(con, "0000320193", datetime(2024, 11, 5, 9))
    seed_filing(con, "0000320193", "10-K", date(2024, 11, 5))
    assert planned(SecCompanyFacts(slice_file("AAPL")), con) == ["0000320193"]


def test_plan_ignores_non_periodic_filings(con, slice_file):
    fetched(con, "0000320193", datetime(2024, 11, 5, 12))
    seed_filing(con, "0000320193", "8-K", date(2024, 11, 20))
    assert planned(SecCompanyFacts(slice_file("AAPL")), con) == []


def test_parse_tracks_revenue_including_assessed_tax():
    body = (
        b'{"facts":{"us-gaap":{"RevenueFromContractWithCustomerIncludingAssessedTax":'
        b'{"units":{"USD":[{"start":"2025-01-01","end":"2025-12-31","val":5,"accn":"a",'
        b'"fy":2025,"fp":"FY","form":"10-K","filed":"2026-02-01"}]}}}}}'
    )
    rows = SecCompanyFacts("unused").parse(REQ, body)["facts"]
    assert [r["concept"] for r in rows] == ["RevenueFromContractWithCustomerIncludingAssessedTax"]
