"""Utilization import behaviour and cross-import duplicate protection."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import (
    import_billing_sample,
    import_utilization_sample,
    sample_path,
    upload,
)


def test_utilization_without_billing_warns_about_unknown_resources(client: TestClient) -> None:
    response = import_utilization_sample(client)
    body = response.json()

    assert body["status"] == "valid_with_warnings"
    assert body["row_count"] == 2880
    assert body["accepted_row_count"] == 2880
    assert body["rejected_row_count"] == 0
    assert body["currencies"] == []
    assert body["period_start"] == "2026-01-31"
    assert body["period_end"] == "2026-03-01"
    assert body["warning_count"] == 4
    assert {issue["code"] for issue in body["issues"]} == {"resource_not_in_billing"}


def test_utilization_with_billing_is_clean(client: TestClient) -> None:
    import_billing_sample(client)
    body = import_utilization_sample(client).json()

    assert body["status"] == "valid"
    assert body["accepted_row_count"] == 2880
    assert body["warning_count"] == 0
    assert body["stats"]["unknown_resource_count"] == 0

    page = client.get(
        f"/api/imports/{body['id']}/records", params={"limit": 5}
    ).json()
    assert page["kind"] == "utilization"
    assert page["total"] == 2880
    assert len(page["items"]) == 5
    first = page["items"][0]
    assert isinstance(first["cpu_avg_pct"], str)
    assert first["resource_id"].startswith("i-demo-")
    assert first["sample_window_minutes"] == 60


def test_utilization_row_errors(client: TestClient) -> None:
    import_billing_sample(client)
    response = upload(client, "utilization", sample_path("utilization_row_errors.csv"))
    assert response.status_code == 201
    body = response.json()

    assert body["status"] == "partial"
    assert body["row_count"] == 8
    assert body["accepted_row_count"] == 2
    assert body["rejected_row_count"] == 6

    codes = {issue["code"] for issue in body["issues"]}
    assert {
        "duplicate_row",
        "invalid_timestamp",
        "number_out_of_range",
        "negative_number",
        "invalid_integer",
    } <= codes
    assert not {issue["code"] for issue in body["issues"] if issue["severity"] == "error"} - {
        "duplicate_row",
        "invalid_timestamp",
        "number_out_of_range",
        "negative_number",
        "invalid_integer",
    }

    warnings = client.get(
        f"/api/imports/{body['id']}/errors", params={"severity": "warning"}
    ).json()
    assert warnings["total"] == 1
    assert warnings["items"][0]["code"] == "p95_below_average"

    records = client.get(f"/api/imports/{body['id']}/records").json()
    assert records["total"] == 2


def test_forced_utilization_reimport_does_not_double_count(client: TestClient) -> None:
    first = import_utilization_sample(client).json()
    second = upload(
        client, "utilization", sample_path("utilization_sample.csv"), force=True
    )

    assert second.status_code == 201
    body = second.json()
    assert body["id"] != first["id"]
    assert body["status"] == "invalid"
    assert body["accepted_row_count"] == 0
    assert body["rejected_row_count"] == 2880
    assert any(issue["code"] == "duplicate_existing_record" for issue in body["issues"])

    records = client.get(f"/api/imports/{body['id']}/records").json()
    assert records["total"] == 0


def test_exact_duplicate_utilization_file_is_rejected(client: TestClient) -> None:
    import_utilization_sample(client)
    response = upload(client, "utilization", sample_path("utilization_sample.csv"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_import"
