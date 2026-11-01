from pathlib import Path

import pytest

from recon.jobs.sec_tickers import URL, SecTickers

pytestmark = pytest.mark.unit

BODY = (Path(__file__).parent / "fixtures" / "company_tickers_exchange.json").read_bytes()


def test_plan_is_single_request_to_sec_file():
    reqs = list(SecTickers().plan(None))
    assert [(r.url, r.key) for r in reqs] == [(URL, "all")]


def test_job_declares_source_and_name():
    job = SecTickers()
    assert (job.name, job.source) == ("sec_tickers", "sec")


def test_parse_zero_pads_cik_and_maps_ticker_rows():
    tables = SecTickers().parse(next(iter(SecTickers().plan(None))), BODY)
    by_ticker = {r["ticker"]: r for r in tables["tickers"]}
    assert by_ticker["AAPL"]["cik"] == "0000320193"
    assert by_ticker["AAPL"]["exchange"] == "Nasdaq"
    assert by_ticker["TINY"]["exchange"] is None


def test_parse_one_company_per_cik_for_multiple_tickers():
    tables = SecTickers().parse(next(iter(SecTickers().plan(None))), BODY)
    ciks = [r["cik"] for r in tables["companies"]]
    assert sorted(ciks) == sorted(set(ciks))
    assert len(tables["tickers"]) == 5
    assert len(ciks) == 4


def test_keys_cover_every_emitted_table():
    job = SecTickers()
    tables = job.parse(next(iter(job.plan(None))), BODY)
    assert set(tables) <= set(job.keys)
