"""Decimal exactness, masking, encoding and upload guard rails."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.core.config import Settings
from app.db.models import CostRecord
from app.main import create_app
from tests.conftest import sample_path, upload

BILLING_HEADER = (
    "usage_date,provider,account_id,service,resource_id,region,environment,"
    "project,usage_quantity,usage_unit,cost_amount,currency,tag_team,tag_owner\n"
)


def _row(resource_id: str, amount: str, account_id: str = "demo-aws-account-001") -> str:
    return (
        f"2026-02-01,aws,{account_id},Amazon EC2,{resource_id},eu-west-1,dev,sandbox,"
        f"24,Hrs,{amount},USD,platform,platform@example.test\n"
    )


def test_decimal_amounts_roundtrip_exactly_and_sum_in_sql(client: TestClient) -> None:
    content = (
        BILLING_HEADER
        + _row("i-decimal-001", "0.1")
        + _row("i-decimal-002", "0.2")
        + _row("i-decimal-003", "0.0000005")
    )
    response = upload(client, "billing", content.encode(), filename="decimal.csv")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "valid"
    assert body["accepted_row_count"] == 3

    records = client.get(f"/api/imports/{body['id']}/records").json()["items"]
    stored = sorted(item["amount"] for item in records)
    assert stored == ["0.000001", "0.100000", "0.200000"]

    session_factory = client.app.state.db.session_factory
    with session_factory() as session:
        rows = session.query(CostRecord).order_by(CostRecord.id).all()
        assert [row.amount for row in rows] == [
            Decimal("0.100000"),
            Decimal("0.200000"),
            Decimal("0.000001"),
        ]
        # SQLAlchemy materializes SUM as Decimal through the type decorator.
        assert session.scalar(select(func.sum(CostRecord.amount))) == Decimal("0.300001")
        # Underneath, SUM is exact integer addition of micro-units.
        assert session.execute(text("SELECT SUM(amount) FROM cost_records")).scalar() == 300_001


def test_twelve_digit_account_id_is_masked(client: TestClient) -> None:
    content = BILLING_HEADER + _row("i-mask-001", "1.000000", account_id="123456789012")
    response = upload(client, "billing", content.encode(), filename="mask.csv")
    body = response.json()

    assert body["status"] == "valid_with_warnings"
    codes = {issue["code"] for issue in body["issues"]}
    assert "account_id_masked" in codes
    assert body["stats"]["masks_applied"] == 1

    record = client.get(f"/api/imports/{body['id']}/records").json()["items"][0]
    assert record["account_id"] == "****9012"


def test_strict_mode_discards_all_rows_when_any_row_fails(client: TestClient, settings: Settings) -> None:
    settings.strict_imports = True
    response = upload(client, "billing", sample_path("billing_row_errors.csv"))
    assert response.status_code == 201
    body = response.json()

    assert body["status"] == "invalid"
    assert body["accepted_row_count"] == 0
    assert body["rejected_row_count"] == 10
    assert any(issue["code"] == "strict_mode_rejected" for issue in body["issues"])
    assert client.get(f"/api/imports/{body['id']}/records").json()["total"] == 0


def test_invalid_utf8_is_recorded_without_rows(client: TestClient) -> None:
    content = b"usage_date,provider\n\xff\xfe"
    response = upload(client, "billing", content, filename="encoding.csv")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "invalid"
    assert body["accepted_row_count"] == 0
    assert {issue["code"] for issue in body["issues"]} == {"invalid_encoding"}


def test_nul_bytes_are_rejected(client: TestClient) -> None:
    content = b"usage_date,provider\n2026-01-01,aws\x00\n"
    response = upload(client, "billing", content, filename="nul.csv")
    body = response.json()
    assert body["status"] == "invalid"
    assert {issue["code"] for issue in body["issues"]} == {"invalid_encoding"}


def test_non_csv_extension_is_rejected_before_reading(client: TestClient) -> None:
    response = upload(client, "billing", b"whatever", filename="data.txt")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"
    assert client.get("/api/imports").json()["total"] == 0


def test_empty_upload_is_rejected(client: TestClient) -> None:
    response = upload(client, "billing", b"", filename="empty.csv")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "file_empty"
    assert client.get("/api/imports").json()["total"] == 0


def test_oversized_upload_is_rejected(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'oversize.db').as_posix()}",
        max_upload_bytes=64,
        log_level="WARNING",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = upload(client, "billing", b"a" * 65, filename="big.csv")
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "file_too_large"
        assert client.get("/api/imports").json()["total"] == 0


def test_missing_file_field_uses_error_envelope(client: TestClient) -> None:
    response = client.post("/api/imports/billing")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_pagination_validation_rejects_zero_limit(client: TestClient) -> None:
    response = client.get("/api/imports", params={"limit": 0})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"
