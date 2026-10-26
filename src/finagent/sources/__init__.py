"""Pluggable financial data sources."""

from typing import Callable, Protocol


class DataSource(Protocol):
    def get_quote(self, ticker: str) -> dict:
        """Return a flat dict of quote fields (price, change, volume, ...) for one ticker."""
        ...


_SOURCES: dict[str, Callable[[], DataSource]] = {}


def register_source(name: str, factory: Callable[[], DataSource]) -> None:
    _SOURCES[name.lower()] = factory


def get_source(name: str) -> DataSource:
    try:
        return _SOURCES[name.lower()]()
    except KeyError:
        raise ValueError(f"Unknown data source {name!r}. Available: {sorted(_SOURCES)}") from None


def _yfinance() -> DataSource:
    from finagent.sources.yfinance_source import YFinanceSource

    return YFinanceSource()


register_source("yfinance", _yfinance)
