import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import ClassVar

from finagent.data.timeutil import utcnow
from finagent.recon.jobs.base import Request
from finagent.recon.watchlist import load_ciks

URL = "https://data.sec.gov/submissions/CIK{cik}.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class SecSubmissions:
    """Company profile and recent filings (up to ~1000) for each watchlist company."""

    name = "sec_submissions"
    source = "sec"
    keys: ClassVar[dict[str, list[str]]] = {"companies": ["cik"], "filings": ["accession_no"]}

    def __init__(self, slice_file: str | Path):
        self.slice_file = slice_file

    def plan(self, con) -> Iterable[Request]:
        for cik in load_ciks(con, self.slice_file):
            yield Request(URL.format(cik=cik), cik)

    def parse(self, req: Request, body: bytes) -> dict[str, list[dict]]:
        doc = json.loads(body)
        now = utcnow()
        company = {
            "cik": req.key,
            "name": doc.get("name"),
            "sic": doc.get("sic"),
            "sic_desc": doc.get("sicDescription"),
            "state_inc": doc.get("stateOfIncorporation"),
            "fiscal_year_end": doc.get("fiscalYearEnd"),
            "updated_at": now,
        }
        recent = doc["filings"]["recent"]
        filings = []
        for i, accession in enumerate(recent["accessionNumber"]):
            primary_doc = recent["primaryDocument"][i]
            filings.append(
                {
                    "accession_no": accession,
                    "cik": req.key,
                    "form": recent["form"][i],
                    "filed_date": _date(recent["filingDate"][i]),
                    "report_date": _date(recent["reportDate"][i]),
                    "primary_doc": primary_doc,
                    "url": DOC_URL.format(
                        cik=int(req.key), accession=accession.replace("-", ""), doc=primary_doc
                    )
                    if primary_doc
                    else None,
                    "ingested_at": now,
                }
            )
        return {"companies": [company], "filings": filings}
