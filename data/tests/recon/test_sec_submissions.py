from datetime import date
from pathlib import Path

import pytest

from finagent.recon.jobs.base import Request
from finagent.recon.jobs.sec_submissions import SecSubmissions

pytestmark = pytest.mark.component

BODY = (Path(__file__).parent / "fixtures" / "submissions_0000320193.json").read_bytes()
REQ = Request("https://data.sec.gov/submissions/CIK0000320193.json", "0000320193")


def test_declares_name_source_and_keys():
    job = SecSubmissions("unused")
    assert (job.name, job.source) == ("sec_submissions", "sec")
    assert job.keys == {"companies": ["cik"], "filings": ["accession_no"]}


def test_plan_is_one_request_per_watchlist_cik(con, slice_file):
    job = SecSubmissions(slice_file("AAPL", "BRK-A", "BRK-B", "TSLA"))
    reqs = list(job.plan(con))
    assert [r.key for r in reqs] == ["0000320193", "0001067983", "0001318605"]
    assert reqs[0].url == "https://data.sec.gov/submissions/CIK0000320193.json"


def test_parse_enriches_company(con, slice_file):
    company = SecSubmissions("unused").parse(REQ, BODY)["companies"][0]
    assert company["cik"] == "0000320193"
    assert (company["name"], company["sic"], company["sic_desc"]) == (
        "Apple Inc.",
        "3571",
        "Electronic Computers",
    )
    assert (company["state_inc"], company["fiscal_year_end"]) == ("CA", "0928")


def test_parse_filings_have_typed_dates_and_document_url():
    filings = {f["accession_no"]: f for f in SecSubmissions("unused").parse(REQ, BODY)["filings"]}
    tenk = filings["0000320193-24-000123"]
    assert (tenk["cik"], tenk["form"]) == ("0000320193", "10-K")
    assert tenk["filed_date"] == date(2024, 11, 1)
    assert tenk["report_date"] == date(2024, 9, 28)
    assert tenk["url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    )


def test_parse_blank_report_date_is_null():
    filings = {f["accession_no"]: f for f in SecSubmissions("unused").parse(REQ, BODY)["filings"]}
    assert filings["0000320193-24-000090"]["report_date"] is None
    assert len(filings) == 3
