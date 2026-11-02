import pytest
from fastapi.testclient import TestClient

from finagent.api.app import create_app
from finagent.api.config import ApiSettings
from finagent.data.db import connect, upsert

pytestmark = pytest.mark.component

TICKERS = [
    {"ticker": "AAPL", "cik": "0000320193", "exchange": "Nasdaq"},
    {"ticker": "A_B", "cik": "0000000002", "exchange": "NYSE"},
    {"ticker": "ABC", "cik": "0000000003", "exchange": "NYSE"},
    {"ticker": "ZZZ", "cik": "0000000004", "exchange": None},
]


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "t.db"
    con = connect(path)
    upsert(con, "tickers", TICKERS, ["ticker"])
    upsert(
        con,
        "public_float",
        [{"cik": f"000000000{i}", "period_end": "2026-06-30", "value": v} for i, v in
         enumerate([5.0, 50.0, 500.0, 5000.0], start=1)],
        ["cik", "period_end"],
    )  # fmt: skip
    con.close()
    return TestClient(
        base_url="http://localhost", app=create_app(ApiSettings(db_path=path, _env_file=None))
    )


def rows(client, table="tickers", **params):
    r = client.get(f"/v1/tables/{table}/rows", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_lists_tables_then_views_with_columns(client):
    got = client.get("/v1/tables").json()
    kinds = [t["kind"] for t in got]
    assert kinds == sorted(kinds)  # tables first
    by_name = {t["name"]: t for t in got}
    assert by_name["tickers"]["kind"] == "table"
    assert [c["name"] for c in by_name["tickers"]["columns"]][:2] == ["ticker", "cik"]
    assert by_name["v_small_cap_candidates"]["kind"] == "view"
    assert not any(n.startswith("sqlite_") for n in by_name)


def test_sort_page_and_total(client):
    page = rows(client, sort="ticker", order="desc", limit=2, offset=1)
    assert [r["ticker"] for r in page["rows"]] == ["A_B", "ABC"]  # byte order: "_" > "B"
    assert page["total"] == 4 and (page["limit"], page["offset"]) == (2, 1)


def test_nulls_sort_last_both_ways(client):
    for order in ("asc", "desc"):
        assert rows(client, sort="exchange", order=order)["rows"][-1]["ticker"] == "ZZZ"


@pytest.mark.parametrize(
    ("flt", "expected"),
    [
        ("exchange:eq:NYSE", ["A_B", "ABC"]),
        ("exchange:ne:NYSE", ["AAPL"]),  # NULL is neither equal nor unequal
        ("ticker:contains:_", ["A_B"]),  # LIKE wildcards are literal
        ("ticker:contains:ap", ["AAPL"]),  # case-insensitive
        ("ticker:starts:A", ["A_B", "AAPL", "ABC"]),
        ("exchange:null:", ["ZZZ"]),
        ("exchange:notnull:", ["A_B", "AAPL", "ABC"]),
    ],
)
def test_text_filters(client, flt, expected):
    assert sorted(r["ticker"] for r in rows(client, filter=flt)["rows"]) == sorted(expected)


def test_numeric_filters_compare_as_numbers_and_combine(client):
    got = rows(client, "public_float", filter=["value:gte:50", "value:lt:5000"], sort="value")
    assert [r["value"] for r in got["rows"]] == [50.0, 500.0] and got["total"] == 2


def test_views_are_browsable(client):
    assert rows(client, "v_small_cap_candidates")["total"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"filter": "nope:eq:1"},
        {"filter": "ticker:like:1"},
        {"filter": "ticker"},
        {"sort": "nope"},
        {"sort": 'ticker" ; DROP TABLE tickers; --'},
        {"order": "sideways"},
    ],
)
def test_bad_requests_are_422(client, params):
    assert client.get("/v1/tables/tickers/rows", params=params).status_code == 422
    assert rows(client)["total"] == 4  # nothing dropped


def test_unknown_table_is_404(client):
    assert client.get('/v1/tables/tickers"--/rows').status_code == 404
    assert client.get("/v1/tables/sqlite_master/rows").status_code == 404
