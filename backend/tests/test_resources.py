"""Resource health inventory: window, aggregation, thresholds and filters."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from tests.conftest import import_billing_sample, import_utilization_sample


def _prepare(client: TestClient) -> None:
    import_billing_sample(client)
    import_utilization_sample(client)


def test_empty_database_returns_an_empty_inventory(client: TestClient) -> None:
    response = client.get("/api/resources")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["contains_sample_data"] is False
    assert any("not findings" in note for note in body["notes"])


def test_inventory_aggregates_utilization_and_cost(client: TestClient) -> None:
    _prepare(client)
    response = client.get("/api/resources", params={"limit": 10})
    assert response.status_code == 200, response.text
    body = response.json()

    # Only resources with both billing and utilization appear (4 of 8 billed).
    assert body["total"] == 4
    assert body["window"] == {"start": "2026-01-31", "end": "2026-03-01", "days": 30}
    items = {item["resource_id"]: item for item in body["items"]}
    assert set(items) == {
        "i-demo-0a1b2c3d4e5f",
        "i-demo-0a1b2c3d4e60",
        "i-demo-0a1b2c3d4e61",
        "vm-demo-azure-001",
    }

    idle = items["i-demo-0a1b2c3d4e60"]
    assert idle["observation_days"] == 30
    assert idle["sample_count"] == 720
    assert Decimal(idle["cpu_avg_pct"]) == Decimal("2.501")
    assert Decimal(idle["cpu_p95_max_pct"]) == Decimal("9.958")
    assert Decimal(idle["memory_avg_pct"]) == Decimal("17.03")
    assert Decimal(idle["memory_p95_max_pct"]) == Decimal("25.693")
    assert idle["idle_candidate"] is True
    assert idle["rightsize_candidate"] is True
    assert idle["owner"] == "unassigned" or idle["owner"] == "platform@example.test"
    assert idle["environment"] in {"staging", "prod", "dev"}
    assert idle["currency"] == "USD"
    assert Decimal(idle["window_cost"]) > 0

    active = items["vm-demo-azure-001"]
    assert active["idle_candidate"] is False
    assert active["rightsize_candidate"] is False
    assert Decimal(active["cpu_avg_pct"]) == Decimal("51.036")

    busy = items["i-demo-0a1b2c3d4e5f"]
    assert busy["idle_candidate"] is False
    assert busy["rightsize_candidate"] is True

    # Costs are per currency and only cover the listed resources.
    summary = client.get("/api/costs/summary").json()
    usd = next(item["amount"] for item in summary["totals"] if item["currency"] == "USD")
    listed = sum(Decimal(item["window_cost"]) for item in body["items"])
    assert listed < Decimal(usd)

    thresholds = body["thresholds"]
    assert thresholds["idle_cpu_p95_pct"] == "15"
    assert thresholds["min_observation_days"] == "14"


def test_inventory_filters_and_scope_errors(client: TestClient) -> None:
    _prepare(client)
    prod = client.get("/api/resources", params={"environment": "prod"}).json()
    assert prod["total"] >= 1
    assert {item["environment"] for item in prod["items"]} == {"prod"}

    missing = client.get("/api/resources", params={"project": "does-not-exist"}).json()
    assert missing["total"] == 0

    invalid = client.get(
        "/api/resources", params={"start": "2026-03-02", "end": "2026-03-01"}
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_date_range"


def test_inventory_pagination(client: TestClient) -> None:
    _prepare(client)
    first = client.get("/api/resources", params={"limit": 2, "offset": 0}).json()
    second = client.get("/api/resources", params={"limit": 2, "offset": 2}).json()
    assert first["total"] == second["total"] == 4
    assert len(first["items"]) == len(second["items"]) == 2
    assert {
        item["resource_id"] for item in first["items"]
    }.isdisjoint({item["resource_id"] for item in second["items"]})


def test_inventory_reports_short_observation_windows(client: TestClient) -> None:
    _prepare(client)
    response = client.get(
        "/api/resources", params={"start": "2026-02-28", "end": "2026-03-01"}
    )
    body = response.json()
    assert body["window"]["days"] == 2
    assert body["total"] == 4
    for item in body["items"]:
        assert item["observation_days"] <= 2
        assert item["idle_candidate"] is False
        assert item["rightsize_candidate"] is False
        assert any("required for a finding" in warning for warning in item["warnings"])
