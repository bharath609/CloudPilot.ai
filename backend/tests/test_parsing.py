"""Structural CSV parsing rules (no database required)."""

from __future__ import annotations

import pytest

from app.services.ingestion.csv_reader import (
    BILLING_COLUMNS,
    CsvStructuralError,
    parse_csv,
)

HEADER = ",".join(BILLING_COLUMNS)
VALID_ROW = (
    "2026-01-01,aws,demo-aws-account-001,Amazon EC2,i-001,eu-west-1,prod,"
    "checkout,24,Hrs,4.608,USD,platform,platform@example.test"
)


def _parse(content: str, *, max_rows: int = 100):
    return parse_csv(content.encode("utf-8"), required_columns=BILLING_COLUMNS, max_rows=max_rows)


def test_bom_crlf_and_quoted_commas_are_supported() -> None:
    row = VALID_ROW.replace("Amazon EC2", '"Amazon, EC2"')
    parsed = _parse("\ufeff" + HEADER + "\r\n" + row + "\r\n")
    assert len(parsed.rows) == 1
    assert parsed.rows[0].values["service"] == "Amazon, EC2"
    assert parsed.rows[0].values["usage_quantity"] == "24"


def test_headers_are_trimmed_and_lowercased() -> None:
    header = ",".join(
        f" {column.upper()} " for column in BILLING_COLUMNS
    )
    parsed = _parse(header + "\n" + VALID_ROW + "\n")
    assert parsed.headers == list(BILLING_COLUMNS)
    assert parsed.rows[0].values["provider"] == "aws"


def test_blank_lines_are_counted_without_breaking_row_numbers() -> None:
    parsed = _parse("\n" + HEADER + "\n\n" + VALID_ROW + "\n\n")
    assert len(parsed.rows) == 1
    assert parsed.rows[0].number == 1
    assert parsed.blank_rows == 3


def test_duplicate_header_is_structural_error() -> None:
    with pytest.raises(CsvStructuralError) as excinfo:
        _parse(HEADER + ",usage_date\n" + VALID_ROW + ",2026-01-01\n")
    assert excinfo.value.issues[0].code == "duplicate_header"


def test_blank_header_is_structural_error() -> None:
    with pytest.raises(CsvStructuralError) as excinfo:
        _parse(HEADER + ",\n" + VALID_ROW + ",x\n")
    assert excinfo.value.issues[0].code == "blank_header"


def test_missing_columns_lists_each_missing_field() -> None:
    with pytest.raises(CsvStructuralError) as excinfo:
        parse_csv(
            b"usage_date,provider\n2026-01-01,aws\n",
            required_columns=BILLING_COLUMNS,
            max_rows=10,
        )
    codes = {issue.code for issue in excinfo.value.issues}
    assert codes == {"missing_columns"}
    missing = {issue.column for issue in excinfo.value.issues}
    assert "cost_amount" in missing
    assert len(missing) == len(BILLING_COLUMNS) - 2


def test_row_field_count_is_reported_per_row_not_fatally() -> None:
    parsed = _parse(HEADER + "\n2026-01-01,aws\n" + VALID_ROW + "\n")
    assert len(parsed.rows) == 2
    assert parsed.rows[0].malformed is True
    assert parsed.rows[1].malformed is False
    assert parsed.issues[0].code == "row_field_count"
    assert parsed.issues[0].row_number == 1


def test_header_without_data_rows_is_invalid() -> None:
    with pytest.raises(CsvStructuralError) as excinfo:
        _parse(HEADER + "\n")
    assert excinfo.value.issues[0].code == "no_data_rows"


def test_row_limit_is_enforced() -> None:
    with pytest.raises(CsvStructuralError) as excinfo:
        _parse(HEADER + "\n" + VALID_ROW + "\n" + VALID_ROW + "\n", max_rows=1)
    assert excinfo.value.issues[0].code == "too_many_rows"


def test_empty_and_whitespace_files_are_invalid() -> None:
    with pytest.raises(CsvStructuralError) as excinfo:
        _parse("")
    assert excinfo.value.issues[0].code == "file_empty"

    with pytest.raises(CsvStructuralError) as excinfo:
        _parse("   \n\n")
    assert excinfo.value.issues[0].code == "no_header"


def test_unterminated_quote_is_structural_error() -> None:
    with pytest.raises(CsvStructuralError) as excinfo:
        _parse(HEADER + '\n2026-01-01,aws,"unterminated\n')
    assert excinfo.value.issues[0].code == "invalid_csv_structure"


def test_float_precision_is_not_applied_during_parsing() -> None:
    parsed = _parse(HEADER + "\n" + VALID_ROW.replace("4.608", "4.608123456789") + "\n")
    assert parsed.rows[0].values["cost_amount"] == "4.608123456789"
