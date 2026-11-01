import logging

import pytest

from recon.watchlist import WatchlistError, load_ciks

pytestmark = pytest.mark.component


def test_maps_tickers_to_ciks_in_file_order(con, slice_file):
    assert load_ciks(con, slice_file("TSLA", "AAPL")) == ["0001318605", "0000320193"]


def test_ignores_blank_lines_comments_case_and_whitespace(con, slice_file):
    path = slice_file("# my list", "", "  aapl  ", "tsla  # electric cars")
    assert load_ciks(con, path) == ["0000320193", "0001318605"]


def test_share_classes_resolve_to_one_cik(con, slice_file):
    assert load_ciks(con, slice_file("BRK-A", "BRK-B")) == ["0001067983"]


def test_unknown_tickers_are_skipped_and_logged(con, slice_file, caplog):
    with caplog.at_level(logging.WARNING):
        assert load_ciks(con, slice_file("AAPL", "NOPE")) == ["0000320193"]
    assert "NOPE" in caplog.text


def test_missing_file_raises_with_path(con, tmp_path):
    with pytest.raises(WatchlistError, match="slice.txt"):
        load_ciks(con, tmp_path / "slice.txt")


def test_no_resolvable_tickers_raises_with_hint(con, slice_file):
    with pytest.raises(WatchlistError, match="sec_tickers"):
        load_ciks(con, slice_file("NOPE"))
