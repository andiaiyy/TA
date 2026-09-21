"""
Timestamp utilities for consistent ISO-8601 formatting.
"""
from datetime import datetime, timezone


def now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
