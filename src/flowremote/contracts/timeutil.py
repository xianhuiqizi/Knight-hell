"""Time handling: one format for the whole project.

SQLite has no native date type and PostgreSQL does, so the project stores
every timestamp as UTC ISO-8601 text, for example 2026-09-30T14:31:00Z. That
is sortable, unambiguous, and identical in both engines.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    """Current UTC time as ISO-8601 text with second precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    """Parse a timestamp written by ``utc_now`` back into a datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
