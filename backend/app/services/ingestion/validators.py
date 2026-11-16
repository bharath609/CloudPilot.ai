"""Field-level validation and normalization.

Every validator returns typed values (``Decimal``, ``date``, ``datetime``) or
records a precise issue. Nothing here touches the database, which keeps the
rules cheap to test and reuse for future provider adapters.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.config import Settings
from app.core.enums import ENVIRONMENTS, PROVIDERS, Severity
from app.core.time import earliest_allowed_date, latest_allowed_date
from app.services.ingestion.csv_reader import BILLING_COLUMNS, UTILIZATION_COLUMNS, ParsedCsv
from app.services.ingestion.types import (
    CostDraft,
    CsvRow,
    FieldIssue,
    MetricDraft,
    ValidationOutcome,
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})?$"
)
_DECIMAL = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_INTEGER = re.compile(r"^[+-]?\d+$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9_*\-]+$")
_RESOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]*$")
_USAGE_UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/\-]*$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_AWS_ACCOUNT_NUMBER = re.compile(r"^\d{12}$")


def _raw(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value[:200]


class RowReader:
    """Reads one CSV row, collecting issues instead of raising on bad fields."""

    def __init__(self, row: CsvRow, issues: list[FieldIssue]) -> None:
        self.row = row
        self._issues = issues
        self.error_count = 0
        self.warning_count = 0
        self.mask_count = 0

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    def value(self, column: str) -> str:
        return self.row.values.get(column, "")

    def add_error(
        self, code: str, message: str, *, column: str | None = None, raw: str | None = None
    ) -> None:
        self._issues.append(
            FieldIssue(
                code=code,
                message=message,
                row_number=self.row.number,
                column=column,
                severity=Severity.ERROR,
                raw_value=_raw(raw),
            )
        )
        self.error_count += 1

    def add_warning(
        self, code: str, message: str, *, column: str | None = None, raw: str | None = None
    ) -> None:
        self._issues.append(
            FieldIssue(
                code=code,
                message=message,
                row_number=self.row.number,
                column=column,
                severity=Severity.WARNING,
                raw_value=_raw(raw),
            )
        )
        self.warning_count += 1

    # -- text -------------------------------------------------------------
    def text(
        self,
        column: str,
        *,
        max_len: int,
        required: bool = True,
        default: str | None = None,
    ) -> str | None:
        value = self.value(column)
        if not value:
            if required:
                self.add_error("required", f"'{column}' is required.", column=column)
                return None
            return default
        if len(value) > max_len:
            self.add_error(
                "too_long",
                f"'{column}' must be at most {max_len} characters (got {len(value)}).",
                column=column,
                raw=value,
            )
            return None
        if _CONTROL_CHARS.search(value):
            self.add_error(
                "invalid_text",
                f"'{column}' contains control characters.",
                column=column,
                raw=value,
            )
            return None
        return value

    def account_id(self) -> str | None:
        value = self.text("account_id", max_len=64)
        if value is None:
            return None
        if len(value) < 3 or not _ACCOUNT_ID.match(value):
            self.add_error(
                "invalid_account_id",
                "account_id must be 3-64 characters using letters, digits, '_', '-' or '*'.",
                column="account_id",
                raw=value,
            )
            return None
        if _AWS_ACCOUNT_NUMBER.match(value):
            masked = "****" + value[-4:]
            self.mask_count += 1
            self.add_warning(
                "account_id_masked",
                "A 12-digit account identifier was detected and masked before storage.",
                column="account_id",
                raw=value,
            )
            return masked
        return value

    def resource_id(self, column: str = "resource_id") -> str | None:
        value = self.text(column, max_len=200)
        if value is None:
            return None
        if not _RESOURCE_ID.match(value):
            self.add_error(
                "invalid_resource_id",
                f"'{column}' has an unsupported format (allowed: letters, digits, . _ : / @ + -).",
                column=column,
                raw=value,
            )
            return None
        return value

    def usage_unit(self, *, known_units: frozenset[str]) -> str | None:
        value = self.text("usage_unit", max_len=32)
        if value is None:
            return None
        if not _USAGE_UNIT.match(value):
            self.add_error(
                "invalid_unit",
                "usage_unit contains unsupported characters.",
                column="usage_unit",
                raw=value,
            )
            return None
        if value.lower() not in known_units:
            self.add_warning(
                "unknown_unit",
                f"usage_unit '{value}' is not in the known unit list; it is stored verbatim.",
                column="usage_unit",
                raw=value,
            )
        return value

    # -- numbers ----------------------------------------------------------
    def decimal(
        self,
        column: str,
        *,
        minimum: Decimal | None = None,
        maximum: Decimal | None = None,
        scale: int = 6,
        required: bool = True,
        default: Decimal | None = None,
    ) -> Decimal | None:
        raw = self.value(column)
        if not raw:
            if required:
                self.add_error("required", f"'{column}' is required.", column=column)
                return None
            return default
        if len(raw) > 64 or not _DECIMAL.match(raw):
            self.add_error(
                "invalid_number",
                f"'{column}' is not a valid number.",
                column=column,
                raw=raw,
            )
            return None
        try:
            value = Decimal(raw)
        except InvalidOperation:
            self.add_error("invalid_number", f"'{column}' is not a valid number.", column=column, raw=raw)
            return None
        if not value.is_finite():
            self.add_error("invalid_number", f"'{column}' must be finite.", column=column, raw=raw)
            return None
        if value < 0:
            self.add_error("negative_number", f"'{column}' must not be negative.", column=column, raw=raw)
            return None
        if minimum is not None and value < minimum:
            self.add_error(
                "number_out_of_range",
                f"'{column}' must be at least {minimum}.",
                column=column,
                raw=raw,
            )
            return None
        if maximum is not None and value > maximum:
            self.add_error(
                "number_out_of_range",
                f"'{column}' must be at most {maximum}.",
                column=column,
                raw=raw,
            )
            return None
        return value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)

    def integer(
        self,
        column: str,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int | None:
        raw = self.value(column)
        if not raw:
            self.add_error("required", f"'{column}' is required.", column=column)
            return None
        if len(raw) > 20 or not _INTEGER.match(raw):
            self.add_error("invalid_integer", f"'{column}' must be a whole number.", column=column, raw=raw)
            return None
        value = int(raw)
        if minimum is not None and value < minimum:
            self.add_error(
                "number_out_of_range",
                f"'{column}' must be at least {minimum}.",
                column=column,
                raw=raw,
            )
            return None
        if maximum is not None and value > maximum:
            self.add_error(
                "number_out_of_range",
                f"'{column}' must be at most {maximum}.",
                column=column,
                raw=raw,
            )
            return None
        if value < 0:
            self.add_error("negative_number", f"'{column}' must not be negative.", column=column, raw=raw)
            return None
        return value

    def percentage(self, column: str) -> Decimal | None:
        return self.decimal(
            column,
            minimum=Decimal(0),
            maximum=Decimal(100),
            scale=3,
        )

    # -- dates ------------------------------------------------------------
    def iso_date(self, column: str) -> date | None:
        raw = self.value(column)
        if not raw:
            self.add_error("required", f"'{column}' is required.", column=column)
            return None
        if not _ISO_DATE.match(raw):
            self.add_error(
                "invalid_date",
                f"'{column}' must use the ISO format YYYY-MM-DD.",
                column=column,
                raw=raw,
            )
            return None
        try:
            value = date.fromisoformat(raw)
        except ValueError:
            self.add_error("invalid_date", f"'{column}' is not a real calendar date.", column=column, raw=raw)
            return None
        if not earliest_allowed_date() <= value <= latest_allowed_date():
            self.add_error(
                "invalid_date",
                f"'{column}' must be between {earliest_allowed_date()} and {latest_allowed_date()}.",
                column=column,
                raw=raw,
            )
            return None
        return value

    def timestamp(self, column: str = "timestamp") -> datetime | None:
        raw = self.value(column)
        if not raw:
            self.add_error("required", f"'{column}' is required.", column=column)
            return None
        if not _ISO_TIMESTAMP.match(raw):
            self.add_error(
                "invalid_timestamp",
                f"'{column}' must be an ISO 8601 timestamp, e.g. 2026-03-01T13:00:00Z.",
                column=column,
                raw=raw,
            )
            return None
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00").replace(" ", "T"))
        except ValueError:
            self.add_error(
                "invalid_timestamp",
                f"'{column}' is not a valid timestamp.",
                column=column,
                raw=raw,
            )
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        if not earliest_allowed_date() <= value.date() <= latest_allowed_date():
            self.add_error(
                "invalid_timestamp",
                f"'{column}' must be between {earliest_allowed_date()} and {latest_allowed_date()}.",
                column=column,
                raw=raw,
            )
            return None
        return value

    # -- enums ------------------------------------------------------------
    def choice(
        self,
        column: str,
        allowed: frozenset[str],
        code: str,
        *,
        default: str | None = None,
    ) -> str | None:
        raw = self.value(column)
        if not raw:
            if default is not None:
                return default
            self.add_error("required", f"'{column}' is required.", column=column)
            return None
        value = raw.lower()
        if value not in allowed:
            self.add_error(
                code,
                f"'{raw}' is not supported for {column}. Allowed: {', '.join(sorted(allowed))}.",
                column=column,
                raw=raw,
            )
            return None
        return value

    def currency(self, column: str, allowed: frozenset[str]) -> str | None:
        raw = self.value(column)
        if not raw:
            self.add_error("required", f"'{column}' is required.", column=column)
            return None
        value = raw.upper()
        if not _CURRENCY.match(value):
            self.add_error(
                "invalid_currency",
                f"'{column}' must be a 3-letter ISO 4217 code.",
                column=column,
                raw=raw,
            )
            return None
        if value not in allowed:
            self.add_error(
                "currency_not_allowed",
                f"Currency {value} is not enabled. Allowed: {', '.join(sorted(allowed))}.",
                column=column,
                raw=raw,
            )
            return None
        return value


def validate_billing(
    parsed: ParsedCsv,
    settings: Settings,
    *,
    existing_keys: set[tuple[object, ...]] | None = None,
) -> ValidationOutcome:
    issues: list[FieldIssue] = list(parsed.issues)
    drafts: list[CostDraft] = []
    rejected = 0
    seen: dict[tuple[object, ...], int] = {}
    currencies: set[str] = set()
    providers: set[str] = set()
    observed_dates: list[date] = []
    masks = 0
    duplicates_in_file = 0
    duplicates_existing = 0

    for row in parsed.rows:
        if row.malformed:
            rejected += 1
            continue

        reader = RowReader(row, issues)
        usage_date = reader.iso_date("usage_date")
        provider = reader.choice("provider", PROVIDERS, "invalid_provider")
        account_id = reader.account_id()
        service = reader.text("service", max_len=80)
        resource_id = reader.resource_id()
        region = reader.text("region", max_len=64)
        environment = reader.choice("environment", ENVIRONMENTS, "invalid_environment", default="unknown")
        project = reader.text("project", max_len=120, required=False, default="unassigned")
        quantity = reader.decimal("usage_quantity", maximum=Decimal("1e15"), scale=6)
        usage_unit = reader.usage_unit(known_units=settings.known_usage_unit_set)
        amount = reader.decimal("cost_amount", maximum=Decimal("1e12"), scale=6)
        currency = reader.currency("currency", settings.allowed_currency_set)
        team = reader.text("tag_team", max_len=80, required=False, default="untagged")
        owner = reader.text("tag_owner", max_len=120, required=False, default="unassigned")

        if reader.value("tag_team") == "":
            reader.add_warning("untagged_team", "tag_team is blank; stored as 'untagged'.", column="tag_team")
        if reader.value("tag_owner") == "":
            reader.add_warning(
                "unowned_resource",
                "tag_owner is blank; stored as 'unassigned'.",
                column="tag_owner",
            )

        masks += reader.mask_count
        if reader.has_errors:
            rejected += 1
            continue

        assert usage_date is not None and provider is not None and account_id is not None
        assert service is not None and resource_id is not None and region is not None
        assert environment is not None and project is not None and quantity is not None
        assert usage_unit is not None and amount is not None and currency is not None
        assert team is not None and owner is not None

        key: tuple[object, ...] = (
            usage_date,
            provider,
            account_id,
            service,
            resource_id,
            usage_unit,
            amount,
        )
        if key in seen:
            reader.add_error(
                "duplicate_row",
                f"Duplicate business key in this file; first seen on data row {seen[key]}.",
                column="resource_id",
                raw=resource_id,
            )
            duplicates_in_file += 1
            rejected += 1
            continue

        seen[key] = row.number
        if existing_keys is not None and key in existing_keys:
            duplicates_existing += 1
            reader.add_warning(
                "duplicate_existing_record",
                "This business key already exists from an earlier import; it is stored again and "
                "may double-count until a dedupe policy is applied.",
            )

        drafts.append(
            CostDraft(
                row_number=row.number,
                usage_date=usage_date,
                provider=provider,
                account_id=account_id,
                service=service,
                resource_id=resource_id,
                region=region,
                environment=environment,
                project=project,
                quantity=quantity,
                usage_unit=usage_unit,
                amount=amount,
                currency=currency,
                tags={"team": team, "owner": owner},
                raw=row.raw,
            )
        )
        currencies.add(currency)
        providers.add(provider)
        observed_dates.append(usage_date)

    for column in _unexpected_columns(parsed, BILLING_COLUMNS):
        issues.append(
            FieldIssue(
                code="unexpected_column",
                message=(
                    f"Column '{column}' is not part of the billing contract; "
                    "it is kept in raw row data only."
                ),
                column=column,
                severity=Severity.WARNING,
            )
        )

    if len(currencies) > 1:
        issues.append(
            FieldIssue(
                code="mixed_currency",
                message=(
                    "This import contains more than one currency "
                    f"({', '.join(sorted(currencies))}). Currencies must never be summed together."
                ),
                severity=Severity.WARNING,
            )
        )

    return ValidationOutcome(
        drafts=drafts,
        issues=issues,
        row_count=len(parsed.rows),
        rejected_rows=rejected,
        currencies=sorted(currencies),
        providers=sorted(providers),
        period_start=min(observed_dates) if observed_dates else None,
        period_end=max(observed_dates) if observed_dates else None,
        stats={
            "blank_rows": parsed.blank_rows,
            "masks_applied": masks,
            "duplicates_in_file": duplicates_in_file,
            "duplicates_existing": duplicates_existing,
        },
    )


def validate_utilization(
    parsed: ParsedCsv,
    settings: Settings,
    *,
    existing_keys: set[tuple[object, ...]] | None = None,
    known_resources: set[str] | None = None,
) -> ValidationOutcome:
    issues: list[FieldIssue] = list(parsed.issues)
    drafts: list[MetricDraft] = []
    rejected = 0
    seen: dict[tuple[object, ...], int] = {}
    observed_dates: list[date] = []
    duplicates_in_file = 0
    duplicates_existing = 0

    for row in parsed.rows:
        if row.malformed:
            rejected += 1
            continue

        reader = RowReader(row, issues)
        observed_at = reader.timestamp("timestamp")
        resource_id = reader.resource_id()
        cpu_avg = reader.percentage("cpu_avg_pct")
        cpu_p95 = reader.percentage("cpu_p95_pct")
        memory_avg = reader.percentage("memory_avg_pct")
        memory_p95 = reader.percentage("memory_p95_pct")
        network_in = reader.integer("network_in_bytes", minimum=0, maximum=10**15)
        network_out = reader.integer("network_out_bytes", minimum=0, maximum=10**15)
        storage_used = reader.percentage("storage_used_pct")
        window = reader.integer("sample_window_minutes", minimum=1, maximum=10080)

        if cpu_avg is not None and cpu_p95 is not None and cpu_p95 < cpu_avg:
            reader.add_warning(
                "p95_below_average",
                "cpu_p95_pct is lower than cpu_avg_pct; the sample may be inconsistent.",
                column="cpu_p95_pct",
            )
        if memory_avg is not None and memory_p95 is not None and memory_p95 < memory_avg:
            reader.add_warning(
                "p95_below_average",
                "memory_p95_pct is lower than memory_avg_pct; the sample may be inconsistent.",
                column="memory_p95_pct",
            )

        if reader.has_errors:
            rejected += 1
            continue

        assert observed_at is not None and resource_id is not None
        assert cpu_avg is not None and cpu_p95 is not None
        assert memory_avg is not None and memory_p95 is not None
        assert network_in is not None and network_out is not None
        assert storage_used is not None and window is not None

        key: tuple[object, ...] = (resource_id, observed_at)
        if key in seen:
            reader.add_error(
                "duplicate_row",
                f"Duplicate resource/timestamp in this file; first seen on data row {seen[key]}.",
                column="resource_id",
                raw=resource_id,
            )
            duplicates_in_file += 1
            rejected += 1
            continue

        seen[key] = row.number
        if existing_keys is not None and key in existing_keys:
            reader.add_error(
                "duplicate_existing_record",
                "A utilization sample already exists for this resource and timestamp.",
                column="resource_id",
                raw=resource_id,
            )
            duplicates_existing += 1
            rejected += 1
            continue

        drafts.append(
            MetricDraft(
                row_number=row.number,
                resource_id=resource_id,
                observed_at=observed_at,
                cpu_avg_pct=cpu_avg,
                cpu_p95_pct=cpu_p95,
                memory_avg_pct=memory_avg,
                memory_p95_pct=memory_p95,
                network_in_bytes=network_in,
                network_out_bytes=network_out,
                storage_used_pct=storage_used,
                sample_window_minutes=window,
            )
        )
        observed_dates.append(observed_at.date())

    for column in _unexpected_columns(parsed, UTILIZATION_COLUMNS):
        issues.append(
            FieldIssue(
                code="unexpected_column",
                message=f"Column '{column}' is not part of the utilization contract; it is ignored.",
                column=column,
                severity=Severity.WARNING,
            )
        )

    unknown_resources: list[str] = []
    if known_resources is not None:
        unknown_resources = sorted(
            {
                draft.resource_id
                for draft in drafts
                if draft.resource_id not in known_resources
            }
        )
        for resource_id in unknown_resources[:50]:
            issues.append(
                FieldIssue(
                    code="resource_not_in_billing",
                    message=(
                        f"Resource '{resource_id}' has no billing records yet; import billing data "
                        "before analysis so savings can be evidence-linked."
                    ),
                    column="resource_id",
                    severity=Severity.WARNING,
                    raw_value=resource_id[:200],
                )
            )

    return ValidationOutcome(
        drafts=drafts,
        issues=issues,
        row_count=len(parsed.rows),
        rejected_rows=rejected,
        currencies=[],
        providers=[],
        period_start=min(observed_dates) if observed_dates else None,
        period_end=max(observed_dates) if observed_dates else None,
        stats={
            "blank_rows": parsed.blank_rows,
            "duplicates_in_file": duplicates_in_file,
            "duplicates_existing": duplicates_existing,
            "unknown_resource_count": len(unknown_resources),
        },
    )


def _unexpected_columns(parsed: ParsedCsv, contract: tuple[str, ...]) -> list[str]:
    allowed = set(contract)
    return [header for header in parsed.headers if header not in allowed]
