"""Billing import: happy path, exact totals, duplicates and audit trail."""

from __future__ import annotations

import csv
from decimal import Decimal

from fastapi.testclient import TestClient

from tests.conftest import import_billing_sample, sample_path, upload


def expected_amount_sum() -> Decimal:
    total = Decimal(0)
    with sample_path("billing_sample.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            total += Decimal(row["cost_amount"])
    return total


def test_valid_billing_import_persists_every_row(client: TestClient) -> None:
    response = import_billing_sample(client)
    body = response.json()

    assert body["kind"] == "billing"
    assert body["status"] == "valid"
    assert body["row_count"] == 480
    assert body["accepted_row_count"] == 480
    assert body["rejected_row_count"] == 0
    assert body["warning_count"] == 0
    assert body["currencies"] == ["USD"]
    assert body["provider"] == "mixed"
    assert body["period_start"] == "2026-01-01"
    assert body["period_end"] == "2026-03-01"
    assert body["issues"] == []
    assert body["issues_truncated"] is False
    assert "Imported 480 rows" in body["message"]

    detail = client.get(f"/api/imports/{body['id']}").json()
    assert detail["issue_count"] == 0
    assert detail["error_count"] == 0
    assert detail["content_bytes"] > 0
    assert detail["content_sha256"] == body["content_sha256"]
    assert detail["stats"]["errors_total"] == 0


def test_api_records_sum_matches_hand_calculated_fixture(client: TestClient) -> None:
    import_id = import_billing_sample(client).json()["id"]

    total = Decimal(0)
    offset = 0
    pages = 0
    while True:
        page = client.get(
            f"/api/imports/{import_id}/records",
            params={"limit": 200, "offset": offset},
        ).json()
        assert page["kind"] == "billing"
        if not page["items"]:
            break
        for item in page["items"]:
            assert isinstance(item["amount"], str), "money must be serialized as a string"
            assert isinstance(item["quantity"], str)
            total += Decimal(item["amount"])
        pages += 1
        offset += page["limit"]

    assert pages == 3
    assert total == expected_amount_sum()


def test_exact_duplicate_upload_is_rejected(client: TestClient) -> None:
    first = import_billing_sample(client).json()

    response = upload(client, "billing", sample_path("billing_sample.csv"))
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "duplicate_import"
    assert error["details"]["import_id"] == first["id"]

    listing = client.get("/api/imports").json()
    assert listing["total"] == 1


def test_forced_reimport_warns_about_overlapping_business_keys(client: TestClient) -> None:
    first = import_billing_sample(client).json()

    second = upload(client, "billing", sample_path("billing_sample.csv"), force=True)
    assert second.status_code == 201
    body = second.json()

    assert body["id"] != first["id"]
    assert body["status"] == "valid_with_warnings"
    assert body["accepted_row_count"] == 480
    assert body["warning_count"] >= 480
    assert any(issue["code"] == "duplicate_existing_record" for issue in body["issues"])

    detail = client.get(f"/api/imports/{body['id']}").json()
    assert detail["stats"]["duplicates_existing"] == 480


def test_billing_row_errors_are_precise_and_do_not_store_bad_rows(client: TestClient) -> None:
    response = upload(client, "billing", sample_path("billing_row_errors.csv"))
    assert response.status_code == 201
    body = response.json()

    assert body["status"] == "partial"
    assert body["row_count"] == 10
    assert body["accepted_row_count"] == 2
    assert body["rejected_row_count"] == 8

    codes = {issue["code"] for issue in body["issues"]}
    assert {
        "duplicate_row",
        "invalid_date",
        "negative_number",
        "currency_not_allowed",
        "invalid_provider",
        "invalid_environment",
        "required",
        "invalid_number",
    } <= codes

    errors = client.get(
        f"/api/imports/{body['id']}/errors", params={"severity": "error", "limit": 200}
    ).json()
    assert errors["total"] == 8
    for issue in errors["items"]:
        assert issue["row_number"] >= 1
        assert issue["message"]
    assert any(issue["column"] == "cost_amount" for issue in errors["items"])

    records = client.get(f"/api/imports/{body['id']}/records").json()
    assert records["total"] == 2
    resource_ids = {item["resource_id"] for item in records["items"]}
    assert resource_ids == {"i-demo-dup-001", "i-demo-dup-009"}


def test_missing_required_column_rejects_entire_file(client: TestClient) -> None:
    response = upload(client, "billing", sample_path("billing_missing_column.csv"))
    assert response.status_code == 201
    body = response.json()

    assert body["status"] == "invalid"
    assert body["row_count"] == 0
    assert body["accepted_row_count"] == 0
    codes = {issue["code"] for issue in body["issues"]}
    assert codes == {"missing_columns"}
    assert any(issue["column"] == "cost_amount" for issue in body["issues"])

    records = client.get(f"/api/imports/{body['id']}/records").json()
    assert records["total"] == 0


def test_mixed_currency_is_flagged_but_stored(client: TestClient) -> None:
    response = upload(client, "billing", sample_path("billing_multicurrency.csv"))
    assert response.status_code == 201
    body = response.json()

    assert body["status"] == "valid_with_warnings"
    assert body["accepted_row_count"] == 2
    assert body["currencies"] == ["EUR", "USD"]
    codes = {issue["code"] for issue in body["issues"]}
    assert "mixed_currency" in codes


def test_list_filters_and_pagination(client: TestClient) -> None:
    import_billing_sample(client)
    upload(client, "billing", sample_path("billing_row_errors.csv"))
    upload(client, "utilization", sample_path("utilization_sample.csv"))

    all_imports = client.get("/api/imports").json()
    assert all_imports["total"] == 3
    assert all_imports["limit"] == 50
    assert len(all_imports["items"]) == 3

    billing = client.get("/api/imports", params={"kind": "billing"}).json()
    assert billing["total"] == 2

    partial = client.get("/api/imports", params={"status": "partial"}).json()
    assert partial["total"] == 1
    assert partial["items"][0]["status"] == "partial"

    paged = client.get("/api/imports", params={"limit": 1, "offset": 1}).json()
    assert paged["total"] == 3
    assert len(paged["items"]) == 1
    assert paged["offset"] == 1

    clamped = client.get("/api/imports", params={"limit": 10_000}).json()
    assert clamped["limit"] == 200


def test_unknown_import_returns_404_envelope(client: TestClient) -> None:
    response = client.get("/api/imports/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
