from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Request:
    url: str
    key: str  # identifies the unit of work (e.g. CIK); used for raw storage and source_state
    optional: bool = False  # a 404 means "nothing there yet", not an error


class Job(Protocol):
    name: str
    source: str  # rate-limit bucket
    keys: dict[str, list[str]]  # table -> upsert key columns

    def plan(self, con) -> Iterable[Request]: ...

    def parse(self, req: Request, body: bytes) -> dict[str, list[dict]]: ...
