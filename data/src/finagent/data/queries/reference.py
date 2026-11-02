import sqlite3

from finagent.data.queries import rows


def get_company(con: sqlite3.Connection, ticker: str) -> dict | None:
    """Company profile by ticker. Profile fields are null until submissions are ingested."""
    found = rows(
        con.execute(
            "SELECT t.ticker, t.cik, t.exchange, c.name, c.sic, c.sic_desc, c.state_inc, "
            "c.fiscal_year_end FROM tickers t LEFT JOIN companies c USING (cik) "
            "WHERE t.ticker = ?",
            [ticker.upper()],
        )
    )
    return found[0] if found else None
