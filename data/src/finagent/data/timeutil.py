from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC timestamp, stored as ISO text in TIMESTAMP columns."""
    return datetime.now(UTC).replace(tzinfo=None)
