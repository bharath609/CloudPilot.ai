"""Layer 1 — Cloud Data Intelligence.

Normalizes collected billing/telemetry metadata, assesses freshness, and enforces
the core rule: every amount keeps its original currency. No FX rate is used,
implied, or stored anywhere in this layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    INR = "INR"


class DataQuality(str, Enum):
    COMPLETE = "complete"
    STALE = "stale"
    MISSING = "missing"
    PARTIAL = "partial"


SUPPORTED_CURRENCIES = {c.value for c in Currency}


def currency_is_valid(code: str) -> bool:
    return code in SUPPORTED_CURRENCIES


def _parse(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def assess_freshness(imported_at: Optional[str], max_age_hours: int = 24) -> Dict[str, Any]:
    """Return freshness facts for the most recent import timestamp."""
    if not imported_at:
        return {
            "data_age_hours": None,
            "freshness_warning": True,
            "data_quality": DataQuality.MISSING.value,
            "note": "No imports found. Upload or seed billing data.",
        }

    parsed = _parse(imported_at)
    if parsed is None:
        return {
            "data_age_hours": None,
            "freshness_warning": True,
            "data_quality": DataQuality.PARTIAL.value,
            "note": "Import timestamp could not be parsed.",
        }

    age_hours = (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0
    stale = age_hours > max_age_hours
    return {
        "data_age_hours": round(age_hours, 1),
        "freshness_warning": stale,
        "data_quality": (DataQuality.STALE if stale else DataQuality.COMPLETE).value,
        "note": (
            f"Data is older than {max_age_hours}h; consider re-importing."
            if stale
            else "Data is within the freshness window."
        ),
    }
