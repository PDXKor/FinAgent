from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC timestamp, matching DuckDB TIMESTAMP columns."""
    return datetime.now(UTC).replace(tzinfo=None)
