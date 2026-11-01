from datetime import date, timedelta

import pytest

from recon.store.db import upsert

pytestmark = pytest.mark.component

AAPL = "0000320193"


def add_company(con):
    upsert(con, "companies", [{"cik": AAPL, "name": "Apple Inc."}], ["cik"])


def add_fact(con, concept, value, end, start=None, fp="FY", form="10-K", unit="USD", filed=None):
    end = date.fromisoformat(end)
    upsert(
        con,
        "facts",
        [
            {
                "cik": AAPL,
                "taxonomy": "us-gaap",
                "concept": concept,
                "unit": unit,
                "period_start": date.fromisoformat(start) if start else end,
                "period_end": end,
                "value": value,
                "fy": end.year,
                "fp": fp,
                "form": form,
                "accession_no": f"{concept}-{end}-{start}-{form}",
                "filed_date": filed or end,
            }
        ],
        ["cik", "taxonomy", "concept", "unit", "period_start", "period_end", "accession_no"],
    )


def test_recent_filings_shows_last_30_days_with_ticker_and_name(con):
    add_company(con)
    today = date.today()
    rows = [
        ("a-new", today - timedelta(days=2), "8-K"),
        ("a-old", today - timedelta(days=45), "10-Q"),
    ]
    upsert(
        con,
        "filings",
        [{"accession_no": a, "cik": AAPL, "form": f, "filed_date": d} for a, d, f in rows],
        ["accession_no"],
    )
    got = con.execute("SELECT ticker, name, form FROM v_recent_filings").fetchall()
    assert got == [("AAPL", "Apple Inc.", "8-K")]


def test_recent_filings_lists_multi_ticker_company_once(con):
    upsert(con, "companies", [{"cik": "0001067983", "name": "Berkshire"}], ["cik"])
    upsert(
        con,
        "filings",
        [{"accession_no": "b1", "cik": "0001067983", "form": "10-Q", "filed_date": date.today()}],
        ["accession_no"],
    )
    assert con.execute("SELECT count(*) FROM v_recent_filings").fetchone()[0] == 1


def financials(con):
    cols = (
        "ticker, name, revenue, net_income, assets, shares_outstanding, "
        "balance_sheet_date, annual_period_end"
    )
    return con.execute(f"SELECT {cols} FROM v_latest_financials").fetchone()


def test_latest_financials_picks_latest_balance_sheet_value(con):
    add_company(con)
    add_fact(con, "Assets", 100, "2023-09-30")
    add_fact(con, "Assets", 120, "2024-06-29", fp="Q3", form="10-Q")
    add_fact(con, "EntityCommonStockSharesOutstanding", 15, "2024-10-18", unit="shares")
    row = financials(con)
    assert row[:2] == ("AAPL", "Apple Inc.")
    assert row[4] == 120 and row[5] == 15
    assert row[6] == date(2024, 6, 29)


def test_latest_financials_uses_only_full_year_flow_values(con):
    add_company(con)
    add_fact(con, "NetIncomeLoss", 90, "2024-09-28", start="2023-10-01")
    add_fact(con, "NetIncomeLoss", 21, "2024-12-28", start="2024-09-29", fp="Q1", form="10-Q")
    add_fact(con, "NetIncomeLoss", 79, "2024-06-29", start="2023-10-01", fp="Q3", form="10-Q")
    row = financials(con)
    assert row[3] == 90
    assert row[7] == date(2024, 9, 28)


def test_latest_financials_merges_both_revenue_concepts(con):
    add_company(con)
    add_fact(con, "Revenues", 300, "2016-09-24", start="2015-09-27")
    add_fact(
        con,
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        400,
        "2023-09-30",
        start="2022-10-01",
    )
    assert financials(con)[2] == 400


def test_latest_financials_counts_revenue_including_assessed_tax(con):
    add_company(con)
    add_fact(
        con,
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        55,
        "2025-12-31",
        start="2025-01-01",
    )
    assert financials(con)[2] == 55


def add_float(con, cik, end, value, accn="a"):
    upsert(
        con,
        "public_float",
        [
            {
                "cik": cik,
                "period_end": date.fromisoformat(end),
                "value": value,
                "accession_no": accn,
                "location": "US-NY",
            }
        ],
        ["cik", "period_end"],
    )


def candidates(con):
    return con.execute(
        "SELECT ticker, name, exchange, public_float, float_date FROM v_small_cap_candidates "
        "ORDER BY ticker"
    ).fetchall()


def test_small_cap_candidates_keep_only_floats_up_to_two_billion(con):
    upsert(
        con,
        "companies",
        [{"cik": AAPL, "name": "Apple"}, {"cik": "0001318605", "name": "Tesla"}],
        ["cik"],
    )
    add_float(con, AAPL, "2025-03-28", 3_000_000_000_000)
    add_float(con, "0001318605", "2025-06-30", 2_000_000_000)  # boundary is inclusive
    assert candidates(con) == [("TSLA", "Tesla", "Nasdaq", 2_000_000_000, date(2025, 6, 30))]


def test_small_cap_candidates_use_each_companys_latest_float(con):
    upsert(con, "companies", [{"cik": AAPL, "name": "Apple"}], ["cik"])
    add_float(con, AAPL, "2024-03-28", 500)
    add_float(con, AAPL, "2025-03-28", 900)
    assert candidates(con) == [("AAPL", "Apple", "Nasdaq", 900, date(2025, 3, 28))]


def test_small_cap_candidates_exclude_zero_float(con):
    upsert(con, "companies", [{"cik": AAPL, "name": "Apple"}], ["cik"])
    add_float(con, AAPL, "2025-03-28", 0)
    assert candidates(con) == []


def test_small_cap_candidates_list_multi_ticker_company_once_under_first_ticker(con):
    upsert(con, "companies", [{"cik": "0001067983", "name": "Berkshire"}], ["cik"])
    add_float(con, "0001067983", "2025-06-30", 1_000)
    assert [r[0] for r in candidates(con)] == ["BRK-A"]
