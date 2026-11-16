"""UTC time helpers.

The application stores and returns timezone-aware UTC timestamps everywhere.
SQLite drops timezone information, so the ORM type decorator re-attaches UTC on
read (see ``app.db.base.UtcDateTime``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def earliest_allowed_date() -> date:
    return date(2000, 1, 1)


def latest_allowed_date() -> date:
    """Allow today plus one day to tolerate timezone boundaries."""

    return (utcnow() + timedelta(days=1)).date()
