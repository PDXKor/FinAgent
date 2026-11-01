import json
from collections.abc import Iterable
from datetime import date
from typing import ClassVar

from recon.jobs.base import Request

URL = "https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/{frame}.json"
QUARTER_ENDS = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def recent_frames(today: date, count: int = 6) -> list[str]:
    """The `count` most recent calendar-quarter frames that have ended, newest first."""
    frames: list[str] = []
    year, quarter = today.year, 4
    while len(frames) < count:
        month, day = QUARTER_ENDS[quarter]
        if date(year, month, day) <= today:
            frames.append(f"CY{year}Q{quarter}I")
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return frames


class SecFrames:
    """Public float for every filer, from SEC XBRL frames.

    A filer reports float as of its fiscal Q2 end, so its value lands in a different calendar
    frame depending on its fiscal year. Six quarters cover every fiscal year plus slack.
    """

    name = "sec_frames"
    source = "sec"
    keys: ClassVar[dict[str, list[str]]] = {"public_float": ["cik", "period_end"]}

    def __init__(self, today: date | None = None):
        self.today = today

    def plan(self, con) -> Iterable[Request]:
        for frame in recent_frames(self.today or date.today()):
            # Frames with no filings yet return 404.
            yield Request(URL.format(frame=frame), f"EntityPublicFloat_{frame}", optional=True)

    def parse(self, req: Request, body: bytes) -> dict[str, list[dict]]:
        rows = [
            {
                "cik": str(p["cik"]).zfill(10),
                "period_end": date.fromisoformat(p["end"]),
                "value": p["val"],
                "accession_no": p["accn"],
                "location": p.get("loc"),
            }
            for p in json.loads(body)["data"]
        ]
        return {"public_float": rows}
