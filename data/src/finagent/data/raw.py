from datetime import datetime
from pathlib import Path


def save_raw(
    raw_dir: str | Path, source: str, job: str, key: str, body: bytes, when: datetime
) -> Path:
    """Persist a response body at <raw_dir>/<source>/<job>/<key>/<timestamp>.json."""
    path = Path(raw_dir) / source / job / key / f"{when:%Y%m%dT%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path
