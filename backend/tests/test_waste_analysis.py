"""Waste detection, price provenance and reproducible savings scenarios."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.services.prices import (
    PriceCatalogueError,
    load_price_catalogue,
    resolve_catalogue_path,
)
from tests.conftest import SAMPLE_DIR, import_billing_sample, import_utilization_sample, upload

MONEY = Decimal("0.000001")
BILLING_HEADER = [
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
    "sku",
]
UTILIZATION_HEADER = [
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
]


def _load_catalogue(client: TestClient, settings: Settings):
    session = client.app.state.db.session_factory()
    try:
        return load_price_catalogue(session, resolve_catalogue_path(settings))
    finally:
        session.close()


def _billing_csv(resources: list[dict[str, str]], days: int, end: date) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(BILLING_HEADER)
    for offset in range(days):
        usage_date = end - timedelta(days=days - 1 - offset)
        for resource in resources:
            writer.writerow(
                [
                    usage_date.isoformat(),
                    resource.get("provider", "aws"),
                    resource.get("account_id", "demo-aws-account-001"),
                    resource.get("service", "Amazon EC2"),
                    resource["resource_id"],
                    resource.get("region", "eu-west-1"),
                    resource.get("environment", "dev"),
                    resource.get("project", "sandbox"),
                    "24",
                    "Hrs",
                    resource.get("amount", "10.000000"),
                    resource.get("currency", "USD"),
                    "platform",
                    "platform@example.test",
                    resource.get("sku", ""),
                ]
            )
    return buffer.getvalue().encode()


def _utilization_csv(
    profiles: list[dict[str, str]],
    days: int,
    end: date,
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(UTILIZATION_HEADER)
    end_dt = datetime.combine(end, datetime.min.time()).replace(hour=23)
    start_dt = end_dt - timedelta(days=days) + timedelta(hours=1)
    moment = start_dt
    while moment <= end_dt:
        for profile in profiles:
            writer.writerow(
                [
                    moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    profile["resource_id"],
                    profile.get("cpu_avg_pct", "2.000"),
                    profile.get("cpu_p95_pct", "5.000"),
                    profile.get("memory_avg_pct", "5.000"),
                    profile.get("memory_p95_pct", "10.000"),
                    "1000",
                    "500",
                    "40.000",
                    "60",
                ]
            )
        moment += timedelta(hours=1)
    return buffer.getvalue().encode()


def _upload_pair(client: TestClient, billing: bytes, utilization: bytes):
    response = upload(client, "billing", billing, filename="billing.csv")
    assert response.status_code == 201, response.text
    response = upload(client, "utilization", utilization, filename="utilization.csv")
    assert response.status_code == 201, response.text


def _sample_baseline(resource_id: str, start: date, end: date) -> Decimal:
    total = Decimal(0)
    with (SAMPLE_DIR / "billing_sample.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["resource_id"] != resource_id:
                continue
            usage_date = date.fromisoformat(row["usage_date"])
            if start <= usage_date <= end:
                total += Decimal(row["cost_amount"])
    return total.quantize(MONEY)


def _findings_by_resource(payload: dict) -> dict[str, dict]:
    return {item["resource_id"]: item for item in payload["findings"]}


def test_sku_is_optional_and_stored_without_warning(client: TestClient) -> None:
    response = import_billing_sample(client)
    body = response.json()
    assert body["warning_count"] == 0, body["issues"]
    assert body["accepted_row_count"] == 480

    records = client.get(
        f"/api/imports/{body['id']}/records", params={"limit": 10}
    ).json()
    assert {item["sku"] for item in records["items"]} <= {
        "demo.ec2.c5.2xlarge",
        "demo.ec2.t3.small",
        None,
    }
    assert any(item["sku"] == "demo.ec2.c5.2xlarge" for item in records["items"])

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(BILLING_HEADER[:-1])
    writer.writerow(
        [
            "2026-02-01",
            "aws",
            "demo-aws-account-001",
            "Amazon EC2",
            "i-legacy-001",
            "eu-west-1",
            "dev",
            "sandbox",
            "24",
            "Hrs",
            "10.000000",
            "USD",
            "platform",
            "platform@example.test",
        ]
    )
    legacy = upload(
        client, "billing", buffer.getvalue().encode(), filename="legacy.csv"
    )
    assert legacy.status_code == 201, legacy.text
    assert legacy.json()["warning_count"] == 0, legacy.json()["issues"]
    assert not any(issue["code"] == "unexpected_column" for issue in legacy.json()["issues"])


def test_catalogue_loads_idempotently_and_exposes_provenance(
    client: TestClient, settings: Settings
) -> None:
    first = _load_catalogue(client, settings)
    assert (first.inserted, first.updated, first.total, first.synthetic) == (4, 0, 4, 4)

    second = _load_catalogue(client, settings)
    assert (second.inserted, second.updated, second.total) == (0, 4, 4)

    body = client.get("/api/prices").json()
    assert body["total"] == 4
    assert body["synthetic_count"] == 4
    assert all(item["is_synthetic"] is True for item in body["items"])
    assert all(
        item["source_url"].startswith("https://example.invalid/") for item in body["items"]
    )
    assert any("not vendor prices" in note for note in body["notes"])

    detail = client.get(f"/api/prices/{body['items'][0]['id']}").json()
    assert detail["source_name"] == "CloudPilot synthetic demo catalogue"
    assert detail["replacement_sku"] is None or detail["replacement_sku"].startswith("demo.")
    assert client.get("/api/prices/999999").status_code == 404


def test_catalogue_rejects_unsourced_or_invalid_rows(tmp_path) -> None:
    missing = tmp_path / "missing.csv"
    missing.write_text("provider,sku\naws,demo\n", encoding="utf-8")
    with pytest.raises(PriceCatalogueError, match="missing columns"):
        load_price_catalogue(None, missing)  # parsing fails before any DB use

    invalid = tmp_path / "invalid.csv"
    invalid.write_text(
        "provider,sku,display_name,service,region,usage_unit,unit_price,currency,"
        "effective_from,effective_to,replacement_sku,is_synthetic,source_name,"
        "source_url,source_retrieved_at,notes\n"
        "oracle,x,Name,Compute,eu,Hrs,-1.00,USD,2025-01-01,,,true,Source,"
        "https://example.invalid/p,,bad\n",
        encoding="utf-8",
    )
    with pytest.raises(PriceCatalogueError, match="not supported"):
        load_price_catalogue(None, invalid)


def test_sample_findings_are_exact_and_reproducible(
    client: TestClient, settings: Settings
) -> None:
    import_billing_sample(client)
    import_utilization_sample(client)
    _load_catalogue(client, settings)

    response = client.post("/api/analysis/run", json={})
    assert response.status_code == 200, response.text
    first = response.json()
    run = first["run"]
    assert run["finding_count"] == 3
    assert run["stats"]["findings_by_type"] == {"idle_resource": 2, "over_provisioned": 1}
    assert run["uses_synthetic_prices"] is True
    assert run["cost_window_start"] == "2026-01-31"
    assert run["cost_window_end"] == "2026-03-01"

    by_resource = _findings_by_resource(first)
    assert set(by_resource) == {
        "i-demo-0a1b2c3d4e5f",
        "i-demo-0a1b2c3d4e60",
        "i-demo-0a1b2c3d4e61",
    }

    window_start = date(2026, 1, 31)
    window_end = date(2026, 3, 1)
    expected = {
        resource_id: _sample_baseline(resource_id, window_start, window_end)
        for resource_id in by_resource
    }
    expected_proposed = (
        expected["i-demo-0a1b2c3d4e5f"] * Decimal("0.096000") / Decimal("0.192000")
    ).quantize(MONEY, rounding=ROUND_HALF_UP)
    expected_total = (
        expected["i-demo-0a1b2c3d4e60"]
        + expected["i-demo-0a1b2c3d4e61"]
        + (expected["i-demo-0a1b2c3d4e5f"] - expected_proposed)
    ).quantize(MONEY)
    assert run["total_savings_by_currency"] == {"USD": str(expected_total)}

    for resource_id, item in by_resource.items():
        assert Decimal(item["baseline_monthly_cost"]) == expected[resource_id]
        assert item["currency"] == "USD"
        assert item["scenario"] is not None
        assert item["assumptions"] and item["warnings"]
        assert item["evidence"]["cost_record_ids"]
        assert item["evidence"]["metric_ids"]
        assert item["evidence"]["cost_records_truncated"] is False
        assert item["evidence"]["metric_ids_truncated"] is True

    idle_staging = by_resource["i-demo-0a1b2c3d4e60"]
    assert idle_staging["finding_type"] == "idle_resource"
    assert idle_staging["scenario"]["method"] == "stop_resource"
    assert Decimal(idle_staging["proposed_monthly_cost"]) == Decimal("0.000000")
    assert Decimal(idle_staging["estimated_monthly_savings"]) == expected[
        "i-demo-0a1b2c3d4e60"
    ]
    assert idle_staging["uses_synthetic_prices"] is False
    assert idle_staging["confidence"] == "high"

    rightsize = by_resource["i-demo-0a1b2c3d4e5f"]
    assert rightsize["finding_type"] == "over_provisioned"
    assert rightsize["current_sku"] == "demo.ec2.c5.2xlarge"
    assert rightsize["recommended_sku"] == "demo.ec2.c5.xlarge"
    assert rightsize["scenario"]["method"] == "rightsize_sku"
    assert rightsize["uses_synthetic_prices"] is True
    assert Decimal(rightsize["proposed_monthly_cost"]) == expected_proposed
    assert Decimal(rightsize["estimated_monthly_savings"]) == (
        expected["i-demo-0a1b2c3d4e5f"] - expected_proposed
    ).quantize(MONEY)
    assert rightsize["price_source"]["current"]["is_synthetic"] is True

    second = client.post("/api/analysis/run", json={}).json()
    assert second["run"]["id"] != run["id"]
    assert second["findings"][0]["id"] != first["findings"][0]["id"]
    assert [
        (item["resource_id"], item["estimated_monthly_savings"])
        for item in second["findings"]
    ] == [
        (item["resource_id"], item["estimated_monthly_savings"])
        for item in first["findings"]
    ]

    latest = client.get("/api/findings").json()
    assert latest["run"]["id"] == second["run"]["id"]
    assert latest["total"] == 3
    older = client.get("/api/findings", params={"run_id": run["id"]}).json()
    assert older["run"]["id"] == run["id"]
    assert older["total"] == 3

    detail = client.get(f"/api/findings/{rightsize['id']}").json()
    assert detail["id"] == rightsize["id"]
    assert detail["scenario"]["id"] == rightsize["scenario"]["id"]
    assert client.get("/api/findings/999999").status_code == 404


def test_insufficient_observation_is_not_a_finding(client: TestClient) -> None:
    end = date(2026, 2, 14)
    _upload_pair(
        client,
        _billing_csv([{"resource_id": "i-short-001", "sku": "demo.ec2.c5.2xlarge"}], 1, end),
        _utilization_csv([{"resource_id": "i-short-001"}], 1, end),
    )

    body = client.post("/api/analysis/run", json={}).json()
    assert body["findings"] == []
    assert body["run"]["finding_count"] == 0
    assert body["run"]["stats"]["skipped"]["insufficient_observation"] == 1
    assert any("insufficient" in note for note in body["run"]["notes"])


def test_missing_price_never_invents_savings(client: TestClient) -> None:
    end = date(2026, 2, 14)
    _upload_pair(
        client,
        _billing_csv([{"resource_id": "i-unpriced-001", "sku": "unknown.sku"}], 14, end),
        _utilization_csv(
            [
                {
                    "resource_id": "i-unpriced-001",
                    "cpu_avg_pct": "20.000",
                    "cpu_p95_pct": "40.000",
                    "memory_avg_pct": "20.000",
                    "memory_p95_pct": "50.000",
                }
            ],
            14,
            end,
        ),
    )

    body = client.post("/api/analysis/run", json={}).json()
    assert body["findings"] == []
    assert body["run"]["stats"]["skipped"]["missing_price"] == 1
    assert body["run"]["uses_synthetic_prices"] is False
    assert any("no price or saving was invented" in note for note in body["run"]["notes"])


def test_low_utilization_without_sku_is_skipped(client: TestClient) -> None:
    end = date(2026, 2, 14)
    _upload_pair(
        client,
        _billing_csv([{"resource_id": "i-nosku-001"}], 14, end),
        _utilization_csv(
            [
                {
                    "resource_id": "i-nosku-001",
                    "cpu_avg_pct": "20.000",
                    "cpu_p95_pct": "40.000",
                    "memory_avg_pct": "20.000",
                    "memory_p95_pct": "50.000",
                }
            ],
            14,
            end,
        ),
    )

    body = client.post("/api/analysis/run", json={}).json()
    assert body["findings"] == []
    assert body["run"]["stats"]["skipped"]["missing_sku"] == 1


def test_savings_are_partitioned_by_currency(client: TestClient) -> None:
    end = date(2026, 2, 14)
    resources = [
        {
            "resource_id": "i-usd-001",
            "account_id": "demo-aws-account-002",
            "currency": "USD",
            "environment": "dev",
        },
        {
            "resource_id": "vm-eur-001",
            "provider": "azure",
            "account_id": "demo-azure-002",
            "service": "Virtual Machines",
            "region": "westeurope",
            "currency": "EUR",
            "environment": "dev",
        },
    ]
    _upload_pair(
        client,
        _billing_csv(resources, 14, end),
        _utilization_csv([{"resource_id": item["resource_id"]} for item in resources], 14, end),
    )

    body = client.post("/api/analysis/run", json={}).json()
    assert body["run"]["finding_count"] == 2
    assert body["run"]["total_savings_by_currency"] == {
        "EUR": "140.000000",
        "USD": "140.000000",
    }
    assert any("never be added together" in note for note in body["run"]["notes"])


def test_analysis_requires_billing_data(client: TestClient) -> None:
    response = client.post("/api/analysis/run", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_billing_data"
    assert client.get("/api/findings").json() == {
        "run": None,
        "items": [],
        "total": 0,
        "limit": 50,
        "offset": 0,
    }
