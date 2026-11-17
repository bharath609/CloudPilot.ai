"""Sourced price catalogue loading and lookup.

The catalogue is deliberately explicit: every row carries a source name, a
source URL and an effective date. Rows marked ``is_synthetic`` are demo data and
are never presented as vendor prices. CloudPilot never fetches prices from a
cloud API and never invents a missing price.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, Settings
from app.core.enums import PROVIDERS
from app.db.models import PriceEntry

PRICE_COLUMNS: tuple[str, ...] = (
    "provider",
    "sku",
    "display_name",
    "service",
    "region",
    "usage_unit",
    "unit_price",
    "currency",
    "effective_from",
    "effective_to",
    "replacement_sku",
    "is_synthetic",
    "source_name",
    "source_url",
    "source_retrieved_at",
    "notes",
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})?$"
)
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_BOOL_TRUE = {"true", "1", "yes", "y"}
_BOOL_FALSE = {"false", "0", "no", "n"}
_SKU = re.compile(r"^[A-Za-z0-9._:/@+-]{1,120}$")
_MONEY = Decimal("0.000001")


class PriceCatalogueError(Exception):
    """Raised when a catalogue file cannot be loaded safely."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__(messages[0] if messages else "Invalid price catalogue")
        self.messages = messages


@dataclass(frozen=True, slots=True)
class PriceLoadResult:
    path: Path
    inserted: int
    updated: int
    total: int
    synthetic: int
    real: int


def resolve_catalogue_path(settings: Settings, path: str | Path | None = None) -> Path:
    candidate = Path(path or settings.price_catalogue_path)
    if candidate.is_absolute():
        return candidate
    return (REPO_ROOT / candidate).resolve()


def load_price_catalogue(
    db: Session,
    path: str | Path,
    *,
    commit: bool = True,
) -> PriceLoadResult:
    """Validate a catalogue CSV and upsert it idempotently.

    Identity is ``(provider, sku, region, currency, usage_unit, effective_from)``.
    Re-running the loader updates changed descriptive fields instead of creating
    duplicate prices.
    """

    resolved = Path(path)
    if not resolved.exists():
        raise PriceCatalogueError([f"Price catalogue not found: {resolved}"])

    rows = _read_rows(resolved)
    parsed: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, row in rows:
        try:
            parsed.append(_parse_row(row, line_number))
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        raise PriceCatalogueError(errors[:50])

    inserted = 0
    updated = 0
    synthetic = 0
    for values in parsed:
        if values["is_synthetic"]:
            synthetic += 1
        identity = {
            "provider": values["provider"],
            "sku": values["sku"],
            "region": values["region"],
            "currency": values["currency"],
            "usage_unit": values["usage_unit"],
            "effective_from": values["effective_from"],
        }
        existing = db.scalar(
            select(PriceEntry).where(
                *[getattr(PriceEntry, key) == value for key, value in identity.items()]
            )
        )
        if existing is None:
            db.add(PriceEntry(**values))
            inserted += 1
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            updated += 1

    if commit:
        db.commit()

    return PriceLoadResult(
        path=resolved,
        inserted=inserted,
        updated=updated,
        total=inserted + updated,
        synthetic=synthetic,
        real=len(parsed) - synthetic,
    )


def find_price(
    db: Session,
    *,
    provider: str,
    sku: str,
    region: str,
    currency: str,
    usage_unit: str,
    on_date: date,
) -> PriceEntry | None:
    """Return the latest effective exact price, or ``None``. No fallback guessing."""

    return db.scalar(
        select(PriceEntry)
        .where(
            PriceEntry.provider == provider,
            PriceEntry.sku == sku,
            PriceEntry.region == region,
            PriceEntry.currency == currency,
            PriceEntry.usage_unit == usage_unit,
            PriceEntry.effective_from <= on_date,
            (PriceEntry.effective_to.is_(None)) | (PriceEntry.effective_to >= on_date),
        )
        .order_by(PriceEntry.effective_from.desc(), PriceEntry.id.desc())
        .limit(1)
    )


# -- parsing --------------------------------------------------------------
def _read_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            headers = [(header or "").strip().lower() for header in (reader.fieldnames or [])]
            missing = [column for column in PRICE_COLUMNS if column not in headers]
            if missing:
                raise PriceCatalogueError(
                    [f"Price catalogue is missing columns: {', '.join(missing)}"]
                )
            unexpected = [header for header in headers if header not in PRICE_COLUMNS]
            if unexpected:
                raise PriceCatalogueError(
                    [f"Price catalogue has unsupported columns: {', '.join(unexpected)}"]
                )
            reader.fieldnames = headers
            rows = [
                (number, {key: (value or "").strip() for key, value in row.items()})
                for number, row in enumerate(reader, start=2)
                if any((value or "").strip() for value in row.values())
            ]
    except csv.Error as exc:
        raise PriceCatalogueError([f"Price catalogue is not valid CSV: {exc}"]) from exc

    if not rows:
        raise PriceCatalogueError(["Price catalogue has no data rows."])
    return rows


def _parse_row(row: dict[str, str], line_number: int) -> dict[str, Any]:
    prefix = f"Line {line_number}"

    def required(column: str) -> str:
        value = row.get(column, "")
        if not value:
            raise ValueError(f"{prefix}: '{column}' is required.")
        return value

    provider = required("provider").lower()
    if provider not in PROVIDERS:
        raise ValueError(f"{prefix}: provider '{provider}' is not supported.")

    sku = required("sku")
    if not _SKU.match(sku):
        raise ValueError(f"{prefix}: sku has unsupported characters.")

    usage_unit = required("usage_unit")
    if len(usage_unit) > 32:
        raise ValueError(f"{prefix}: usage_unit is too long.")

    currency = required("currency").upper()
    if not _CURRENCY.match(currency):
        raise ValueError(f"{prefix}: currency must be a 3-letter ISO 4217 code.")

    raw_price = required("unit_price")
    try:
        unit_price = Decimal(raw_price)
    except InvalidOperation as exc:
        raise ValueError(f"{prefix}: unit_price is not a valid number.") from exc
    if not unit_price.is_finite() or unit_price <= 0:
        raise ValueError(f"{prefix}: unit_price must be a positive finite number.")
    unit_price = unit_price.quantize(_MONEY)

    effective_from = _parse_date(required("effective_from"), prefix, "effective_from")
    effective_to_raw = row.get("effective_to", "")
    effective_to = _parse_date(effective_to_raw, prefix, "effective_to") if effective_to_raw else None
    if effective_to is not None and effective_to < effective_from:
        raise ValueError(f"{prefix}: effective_to is before effective_from.")

    replacement_sku = row.get("replacement_sku") or None
    if replacement_sku is not None:
        if not _SKU.match(replacement_sku):
            raise ValueError(f"{prefix}: replacement_sku has unsupported characters.")
        if replacement_sku == sku:
            raise ValueError(f"{prefix}: replacement_sku must differ from sku.")

    source_url = required("source_url")
    if not source_url.lower().startswith(("https://", "http://")):
        raise ValueError(f"{prefix}: source_url must be an http(s) URL.")

    source_name = required("source_name")
    retrieved_raw = row.get("source_retrieved_at", "")
    source_retrieved_at = (
        _parse_timestamp(retrieved_raw, prefix, "source_retrieved_at") if retrieved_raw else None
    )

    notes = row.get("notes") or None
    if notes is not None and len(notes) > 1000:
        raise ValueError(f"{prefix}: notes is longer than 1000 characters.")

    display_name = required("display_name")
    if len(display_name) > 160:
        raise ValueError(f"{prefix}: display_name is longer than 160 characters.")
    service = required("service")
    if len(service) > 80:
        raise ValueError(f"{prefix}: service is longer than 80 characters.")
    region = required("region")
    if len(region) > 64:
        raise ValueError(f"{prefix}: region is longer than 64 characters.")

    return {
        "provider": provider,
        "sku": sku,
        "display_name": display_name,
        "service": service,
        "region": region,
        "usage_unit": usage_unit,
        "unit_price": unit_price,
        "currency": currency,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "replacement_sku": replacement_sku,
        "is_synthetic": _parse_bool(required("is_synthetic"), prefix),
        "source_name": source_name,
        "source_url": source_url,
        "source_retrieved_at": source_retrieved_at,
        "notes": notes,
    }


def _parse_bool(raw: str, prefix: str) -> bool:
    value = raw.strip().lower()
    if value in _BOOL_TRUE:
        return True
    if value in _BOOL_FALSE:
        return False
    raise ValueError(f"{prefix}: is_synthetic must be true or false.")


def _parse_date(raw: str, prefix: str, column: str) -> date:
    if not _ISO_DATE.match(raw):
        raise ValueError(f"{prefix}: {column} must be an ISO date (YYYY-MM-DD).")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{prefix}: {column} is not a valid date.") from exc


def _parse_timestamp(raw: str, prefix: str, column: str) -> datetime:
    if not _ISO_TIMESTAMP.match(raw):
        raise ValueError(f"{prefix}: {column} must be an ISO timestamp.")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError as exc:
        raise ValueError(f"{prefix}: {column} is not a valid timestamp.") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
