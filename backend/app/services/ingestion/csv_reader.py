"""Low-level CSV parsing and structural validation.

This module intentionally uses the standard-library ``csv`` module instead of
pandas: ingestion needs row-accurate error reporting and must never coerce money
through floating point.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

from app.services.ingestion.types import CsvRow, FieldIssue, ParsedCsv

BILLING_COLUMNS: tuple[str, ...] = (
    "usage_date",
    "provider",
    "account_id",
    "service",
    "resource_id",
    "region",
    "environment",
    "project",
    "usage_quantity",
    "usage_unit",
    "cost_amount",
    "currency",
    "tag_team",
    "tag_owner",
)

#: Optional billing columns. Their presence is never a warning; their absence is
#: not an error. ``sku`` links a billing row to a sourced catalogue price.
BILLING_OPTIONAL_COLUMNS: tuple[str, ...] = ("sku",)

UTILIZATION_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "resource_id",
    "cpu_avg_pct",
    "cpu_p95_pct",
    "memory_avg_pct",
    "memory_p95_pct",
    "network_in_bytes",
    "network_out_bytes",
    "storage_used_pct",
    "sample_window_minutes",
)


class CsvStructuralError(Exception):
    """Raised when a file cannot be interpreted as a CSV table at all."""

    def __init__(
        self,
        issues: list[FieldIssue],
        *,
        row_count: int = 0,
        stats: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(issues[0].message if issues else "Invalid CSV file")
        self.issues = issues
        self.row_count = row_count
        self.stats = stats or {}


def _structural(
    code: str, message: str, *, column: str | None = None, raw: str | None = None
) -> CsvStructuralError:
    return CsvStructuralError(
        [FieldIssue(code=code, message=message, column=column, raw_value=raw)]
    )


def parse_csv(
    content: bytes,
    *,
    required_columns: tuple[str, ...],
    max_rows: int,
) -> ParsedCsv:
    """Decode and structurally validate a CSV upload.

    Structural failures raise :class:`CsvStructuralError`. Row-level structural
    problems (wrong field count) are returned as issues and the affected row is
    marked ``malformed`` so the caller can count it as rejected.
    """

    if not content:
        raise _structural("file_empty", "The uploaded file is empty.")

    if b"\x00" in content:
        raise _structural("invalid_encoding", "The file contains NUL bytes and is not a text CSV.")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _structural(
            "invalid_encoding",
            f"The file is not valid UTF-8 (byte offset {exc.start}). Re-export it as UTF-8.",
        ) from exc

    if not text.strip():
        raise _structural("no_header", "The file has no content or header row.")

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=",", strict=True)

    headers: list[str] | None = None
    rows: list[CsvRow] = []
    issues: list[FieldIssue] = []
    blank_rows = 0
    data_row_number = 0

    try:
        for fields in reader:
            if not fields or all(not str(value).strip() for value in fields):
                blank_rows += 1
                continue

            if headers is None:
                headers = [_normalise_header(value) for value in fields]
                _validate_header(headers)
                continue

            data_row_number += 1
            if data_row_number > max_rows:
                raise _structural(
                    "too_many_rows",
                    f"The file contains more than the allowed {max_rows:,} data rows.",
                )

            if len(fields) != len(headers):
                issues.append(
                    FieldIssue(
                        code="row_field_count",
                        message=(
                            f"Expected {len(headers)} fields but found {len(fields)}; "
                            "this row was skipped."
                        ),
                        row_number=data_row_number,
                    )
                )
                rows.append(CsvRow(number=data_row_number, values={}, raw={}, malformed=True))
                continue

            values: dict[str, str] = {}
            raw: dict[str, str] = {}
            for header, value in zip(headers, fields, strict=True):
                value = value if value is not None else ""
                values[header] = value.strip()
                raw[header] = value[:5000]
            rows.append(CsvRow(number=data_row_number, values=values, raw=raw))
    except csv.Error as exc:
        raise _structural(
            "invalid_csv_structure",
            f"The CSV could not be parsed near data row {data_row_number + 1}: {exc}.",
        ) from exc

    if headers is None:
        raise _structural("no_header", "The file has no header row.")

    missing = [column for column in required_columns if column not in headers]
    if missing:
        raise CsvStructuralError(
            [
                FieldIssue(
                    code="missing_columns",
                    message=(
                        f"Required column '{column}' is missing. Expected columns: "
                        + ", ".join(required_columns)
                    ),
                    column=column,
                )
                for column in missing
            ],
            stats={"missing_columns": missing},
        )

    if data_row_number == 0:
        raise CsvStructuralError(
            [
                FieldIssue(
                    code="no_data_rows",
                    message="The file has a header but no data rows.",
                )
            ],
            stats={"blank_rows": blank_rows},
        )

    return ParsedCsv(headers=headers, rows=rows, issues=issues, blank_rows=blank_rows)


def _normalise_header(value: str) -> str:
    return value.replace("\ufeff", "").strip().lower()


def _validate_header(headers: list[str]) -> None:
    seen: set[str] = set()
    for header in headers:
        if not header:
            raise _structural("blank_header", "The header contains an empty column name.")
        if header in seen:
            raise _structural(
                "duplicate_header",
                f"The header contains the column '{header}' more than once.",
                column=header,
            )
        seen.add(header)


@dataclass(slots=True)
class ParsedFile:
    """Wraps bytes plus the parsed table for callers that want both."""

    content_sha256: str
    parsed: ParsedCsv
    extra: dict[str, Any] = field(default_factory=dict)
