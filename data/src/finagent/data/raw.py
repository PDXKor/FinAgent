from datetime import datetime
from pathlib import Path


def save_raw(
    raw_dir: str | Path,
    source: str,
    job: str,
    key: str,
    body: bytes,
    when: datetime,
    keep: int = 0,
) -> Path:
    """Persist a response body at <raw_dir>/<source>/<job>/<key>/<timestamp>.json.

    `keep` > 0 deletes this key's older responses beyond the newest `keep` (reparse reads only
    the newest).
    """
    path = Path(raw_dir) / source / job / key / f"{when:%Y%m%dT%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    if keep > 0:
        for old in sorted(path.parent.glob("*.json"))[:-keep]:
            old.unlink()
    return path
