import sqlite3

from finagent.data.queries import rows


def get_financials(con: sqlite3.Connection, ticker: str, limit: int = 8) -> list[dict]:
    """Annual financials for a ticker, newest fiscal year first. Empty if none."""
    return rows(
        con.execute(
            "SELECT fiscal_year, period_end, revenue, net_income, operating_income, assets, "
            "liabilities, equity, cash, shares_outstanding, form, filed_date "
            "FROM v_annual_financials WHERE cik = (SELECT cik FROM tickers WHERE ticker = ?) "
            "ORDER BY period_end DESC LIMIT ?",
            [ticker.upper(), limit],
        )
    )
