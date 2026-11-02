import json
from collections.abc import Iterable
from typing import ClassVar

from finagent.data.timeutil import utcnow
from finagent.recon.jobs.base import Request

URL = "https://www.sec.gov/files/company_tickers_exchange.json"


def pad_cik(cik: int | str) -> str:
    return str(cik).zfill(10)


class SecTickers:
    name = "sec_tickers"
    source = "sec"
    keys: ClassVar[dict[str, list[str]]] = {"companies": ["cik"], "tickers": ["ticker"]}
    replace: ClassVar[tuple[str, ...]] = ("tickers",)  # the file lists every current ticker

    def plan(self, con) -> Iterable[Request]:
        yield Request(URL, "all")

    def parse(self, req: Request, body: bytes) -> dict[str, list[dict]]:
        doc = json.loads(body)
        now = utcnow()
        companies: dict[str, dict] = {}
        tickers: list[dict] = []
        for row in doc["data"]:
            rec = dict(zip(doc["fields"], row))
            cik = pad_cik(rec["cik"])
            companies.setdefault(cik, {"cik": cik, "name": rec["name"], "updated_at": now})
            tickers.append(
                {
                    "ticker": rec["ticker"],
                    "cik": cik,
                    "exchange": rec["exchange"],
                    "updated_at": now,
                }
            )
        return {"companies": list(companies.values()), "tickers": tickers}
