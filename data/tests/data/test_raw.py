from datetime import datetime

import pytest

from finagent.data.raw import save_raw

pytestmark = pytest.mark.unit


def test_save_raw_writes_under_source_job_key_with_timestamp(tmp_path):
    path = save_raw(tmp_path, "sec", "sec_tickers", "all", b"{}", datetime(2026, 1, 2, 3, 4, 5))
    assert path == tmp_path / "sec" / "sec_tickers" / "all" / "20260102T030405.json"
    assert path.read_bytes() == b"{}"
