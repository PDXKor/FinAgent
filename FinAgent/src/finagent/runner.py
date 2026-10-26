from datetime import datetime, timezone
from pathlib import Path

from finagent.config import Settings, get_settings
from finagent.graph import build_graph
from finagent.llm import get_llm
from finagent.sources import get_source


def run_once(settings: Settings | None = None) -> Path:
    """Run the workflow once and write a timestamped markdown report. Returns its path."""
    s = settings or get_settings()
    graph = build_graph(get_llm(s), get_source(s.data_source))
    result = graph.invoke({"tickers": s.tickers})

    out = Path(s.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"report-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.md"
    path.write_text(result["report"], encoding="utf-8")
    return path
