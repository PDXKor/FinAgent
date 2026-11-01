import logging
from pathlib import Path

log = logging.getLogger(__name__)


class WatchlistError(Exception):
    pass


def load_ciks(con, path: str | Path) -> list[str]:
    """Resolve the tickers in a watchlist file to unique CIKs, preserving file order."""
    path = Path(path)
    if not path.exists():
        raise WatchlistError(f"watchlist not found: {path} (one ticker per line)")
    wanted = []
    for line in path.read_text().splitlines():
        ticker = line.split("#")[0].strip().upper()
        if ticker and ticker not in wanted:
            wanted.append(ticker)
    known = dict(con.execute("SELECT ticker, cik FROM tickers").fetchall())
    ciks: list[str] = []
    for ticker in wanted:
        cik = known.get(ticker)
        if cik is None:
            log.warning("watchlist ticker not found, skipping: %s", ticker)
        elif cik not in ciks:
            ciks.append(cik)
    if not ciks:
        raise WatchlistError(f"no tickers in {path} resolved to a CIK; run `recon run sec_tickers`")
    return ciks
