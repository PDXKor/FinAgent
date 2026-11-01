import pytest

from recon.store.db import connect, upsert

TICKERS = [
    {"ticker": "AAPL", "cik": "0000320193", "exchange": "Nasdaq"},
    {"ticker": "BRK-A", "cik": "0001067983", "exchange": "NYSE"},
    {"ticker": "BRK-B", "cik": "0001067983", "exchange": "NYSE"},
    {"ticker": "TSLA", "cik": "0001318605", "exchange": "Nasdaq"},
]


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    upsert(c, "tickers", TICKERS, ["ticker"])
    yield c
    c.close()


@pytest.fixture
def slice_file(tmp_path):
    """Write a watchlist file and return its path."""

    def make(*lines: str):
        path = tmp_path / "slice.txt"
        path.write_text("\n".join(lines) + "\n")
        return path

    return make
