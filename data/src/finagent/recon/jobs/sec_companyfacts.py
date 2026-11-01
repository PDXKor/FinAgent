import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import ClassVar

from finagent.recon.jobs.base import Request
from finagent.recon.watchlist import load_ciks

URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Keep the table small: headline financials only. Expand as needed.
CONCEPTS = frozenset(
    {
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "NetIncomeLoss",
        "Assets",
        "Liabilities",
        "StockholdersEquity",
        "CashAndCashEquivalentsAtCarryingValue",
        "OperatingIncomeLoss",
        "EntityCommonStockSharesOutstanding",
    }
)
PERIODIC_FORMS = ("10-K", "10-K/A", "10-KT", "10-Q", "10-Q/A")


class SecCompanyFacts:
    """XBRL financials per watchlist company; refetched only after a new periodic filing."""

    name = "sec_companyfacts"
    source = "sec"
    keys: ClassVar[dict[str, list[str]]] = {
        "facts": [
            "cik",
            "taxonomy",
            "concept",
            "unit",
            "period_start",
            "period_end",
            "accession_no",
        ]
    }

    def __init__(self, slice_file: str | Path):
        self.slice_file = slice_file

    def plan(self, con) -> Iterable[Request]:
        marks = ", ".join("?" * len(PERIODIC_FORMS))
        latest_filed = dict(
            con.execute(
                f"SELECT cik, max(filed_date) FROM filings WHERE form IN ({marks}) GROUP BY cik",
                list(PERIODIC_FORMS),
            ).fetchall()
        )
        last_fetched = dict(
            con.execute(
                "SELECT key, last_fetched_at FROM source_state WHERE job = ?", [self.name]
            ).fetchall()
        )
        for cik in load_ciks(con, self.slice_file):
            fetched = last_fetched.get(cik)
            filed = latest_filed.get(cik)
            # Both are ISO text. >= on the date: a filing from the fetch day may have landed
            # after the fetch.
            if fetched is None or (filed is not None and filed >= fetched[:10]):
                yield Request(URL.format(cik=cik), cik)

    def parse(self, req: Request, body: bytes) -> dict[str, list[dict]]:
        rows = []
        for taxonomy, concepts in json.loads(body)["facts"].items():
            for concept, detail in concepts.items():
                if concept not in CONCEPTS:
                    continue
                for unit, points in detail["units"].items():
                    for p in points:
                        end = date.fromisoformat(p["end"])
                        rows.append(
                            {
                                "cik": req.key,
                                "taxonomy": taxonomy,
                                "concept": concept,
                                "unit": unit,
                                "period_start": date.fromisoformat(p["start"])
                                if p.get("start")
                                else end,
                                "period_end": end,
                                "value": p["val"],
                                "fy": p.get("fy"),
                                "fp": p.get("fp"),
                                "form": p.get("form"),
                                "accession_no": p["accn"],
                                "filed_date": date.fromisoformat(p["filed"]),
                            }
                        )
        return {"facts": rows}
