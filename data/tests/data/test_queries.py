from datetime import UTC, date, datetime

import pytest

from finagent.data.db import connect, upsert
from finagent.data.queries.agents import get_agent_run, save_agent_run
from finagent.data.queries.fundamentals import get_financials
from finagent.data.queries.reference import get_company

pytestmark = pytest.mark.component

CIK = "0000320193"
FACT_KEYS = ["cik", "taxonomy", "concept", "unit", "period_start", "period_end", "accession_no"]


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "t.db")
    upsert(c, "tickers", [{"ticker": "AAPL", "cik": CIK, "exchange": "Nasdaq"}], ["ticker"])
    upsert(c, "companies", [{"cik": CIK, "name": "Apple Inc.", "sic_desc": "Computers"}], ["cik"])
    yield c
    c.close()


def add_fact(
    con, concept, value, end, start=None, form="10-K", acc="a1", filed=None, unit="USD", fy=None
):
    """`fy` is the filing's fiscal year (companyfacts semantics); defaults to the period year."""
    upsert(
        con,
        "facts",
        [
            {
                "cik": CIK,
                "taxonomy": "dei" if concept.startswith("Entity") else "us-gaap",
                "concept": concept,
                "unit": unit,
                "period_start": date.fromisoformat(start or end),
                "period_end": date.fromisoformat(end),
                "value": value,
                "fy": fy or int(end[:4]),
                "form": form,
                "accession_no": acc,
                "filed_date": date.fromisoformat(filed or end),
            }
        ],
        FACT_KEYS,
    )


def test_get_company_joins_profile_case_insensitive(con):
    got = get_company(con, "aapl")
    assert got["cik"] == CIK and got["name"] == "Apple Inc." and got["exchange"] == "Nasdaq"
    assert get_company(con, "ZZZZ") is None


def test_get_company_returns_ticker_before_profile_ingested(con):
    upsert(con, "tickers", [{"ticker": "NEW", "cik": "0000000001"}], ["ticker"])
    assert get_company(con, "NEW") == {
        "ticker": "NEW", "cik": "0000000001", "exchange": None, "name": None, "sic": None,
        "sic_desc": None, "state_inc": None, "fiscal_year_end": None,
    }  # fmt: skip


def test_get_financials_one_row_per_fiscal_year_newest_first(con):
    for year, acc in ((2023, "k23"), (2024, "k24")):
        filed = f"{year + 1}-02-01"
        add_fact(con, "Revenues", year * 10, f"{year}-12-31", f"{year}-01-01", acc=acc, filed=filed)
        add_fact(con, "Assets", year * 100, f"{year}-12-31", acc=acc, filed=filed)
    add_fact(con, "Revenues", 5, "2024-03-31", "2024-01-01", form="10-Q", acc="q1")

    got = get_financials(con, "AAPL")
    assert [(r["fiscal_year"], r["revenue"], r["assets"]) for r in got] == [
        (2024, 20240, 202400),
        (2023, 20230, 202300),
    ]
    assert len(get_financials(con, "AAPL", limit=1)) == 1
    assert get_financials(con, "ZZZZ") == []


def test_annual_restatement_wins_but_year_and_shares_come_from_original_10k(con):
    add_fact(con, "Revenues", 100, "2023-12-31", "2023-01-01", acc="k23", filed="2024-02-01")
    add_fact(con, "EntityCommonStockSharesOutstanding", 7, "2024-01-20", acc="k23",
             filed="2024-02-01", unit="shares")  # fmt: skip
    add_fact(
        con, "Revenues", 110, "2023-12-31", "2023-01-01", acc="k24", filed="2025-02-01", fy=2024
    )

    (row,) = get_financials(con, "AAPL")
    assert row["fiscal_year"] == 2023  # from the original 10-K; the comparative says 2024
    assert row["revenue"] == 110
    assert row["shares_outstanding"] == 7
    assert row["filed_date"] == "2024-02-01"


def test_save_agent_run_upserts_and_round_trips_json(con):
    started = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    run = {
        "run_id": "r1", "workflow": "ping", "status": "running", "inputs": {"text": "hi"},
        "output": None, "bindings": {"agent": {"model": "m"}}, "started_at": started,
    }  # fmt: skip
    save_agent_run(con, run)
    save_agent_run(con, {**run, "status": "ok", "output": {"answer": [1, 2]}, "input_tokens": 9})

    got = get_agent_run(con, "r1")
    assert got["status"] == "ok"
    assert got["inputs"] == {"text": "hi"}
    assert got["output"] == {"answer": [1, 2]}
    assert got["input_tokens"] == 9
    assert got["started_at"] == "2026-11-01 12:00:00"  # naive UTC, like every other table
    assert get_agent_run(con, "nope") is None


def test_save_agent_run_rejects_unknown_columns(con):
    with pytest.raises(ValueError, match="bogus"):
        save_agent_run(con, {"run_id": "r1", "bogus": 1})
