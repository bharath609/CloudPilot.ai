"""Cost analytics: hand-calculated totals, currency partitioning and de-duplication."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from tests.conftest import upload

ANALYTICS_CSV = b"""usage_date,provider,account_id,service,resource_id,region,environment,project,usage_quantity,usage_unit,cost_amount,currency,tag_team,tag_owner
2026-01-01,aws,demo-aws-account-001,EC2,i-001,us-east-1,prod,proj-alpha,10,Hrs,10.000000,USD,platform,alice@example.test
2026-01-01,aws,demo-aws-account-001,S3,bucket-002,us-east-1,prod,proj-alpha,5,GB-Mo,5.000000,USD,platform,alice@example.test
2026-01-02,aws,demo-aws-account-001,EC2,i-003,us-east-1,dev,proj-alpha,2.5,Hrs,2.500000,USD,platform,bob@example.test
2026-01-02,azure,demo-azure-account-001,SQL,rds-004,eastus,dev,proj-beta,4,Hrs,4.000000,EUR,data,carol@example.test
2026-02-03,gcp,demo-gcp-account-001,BigQuery,q-005,us-central1,staging,proj-beta,1,TB,7.250000,USD,data,dan@example.test
"""


def _import_analytics(client: TestClient, *, force: bool = False):
    response = upload(client, "billing", ANALYTICS_CSV, filename="analytics.csv", force=force)
    assert response.status_code == 201, response.text
    return response


def _amounts(payload: dict) -> dict[str, Decimal]:
    return {item["currency"]: Decimal(item["amount"]) for item in payload["totals"]}


def test_summary_totals_match_hand_calculation(client: TestClient) -> None:
    _import_analytics(client)

    response = client.get("/api/costs/summary")
    assert response.status_code == 200, response.text
    body = response.json()

    assert _amounts(body) == {"USD": Decimal("24.750000"), "EUR": Decimal("4.000000")}
    assert body["row_count"] == 5
    assert body["excluded_duplicate_rows"] == 0
    assert body["window"] == {"start": "2026-01-01", "end": "2026-02-03", "days": 34}
    assert body["contains_sample_data"] is False
    assert body["import_count"] == 1
    assert any("no FX conversion" in note for note in body["notes"])
    assert any("do not add them together" in note for note in body["notes"])


def test_summary_can_filter_one_currency(client: TestClient) -> None:
    _import_analytics(client)

    body = client.get("/api/costs/summary", params={"currency": "usd"}).json()
    assert _amounts(body) == {"USD": Decimal("24.750000")}
    assert body["row_count"] == 4


def test_breakdown_shares_are_per_currency(client: TestClient) -> None:
    _import_analytics(client)

    body = client.get("/api/costs/breakdown", params={"dimension": "service"}).json()
    assert body["dimension"] == "service"
    assert body["total_groups"] == 4
    assert body["items_truncated"] is False

    items = [
        (item["currency"], item["key"], Decimal(item["amount"]), Decimal(item["share_pct"]))
        for item in body["items"]
    ]
    assert items == [
        ("EUR", "SQL", Decimal("4.000000"), Decimal("100.000")),
        ("USD", "EC2", Decimal("12.500000"), Decimal("50.505")),
        ("USD", "BigQuery", Decimal("7.250000"), Decimal("29.293")),
        ("USD", "S3", Decimal("5.000000"), Decimal("20.202")),
    ]
    usd_share = sum(item[3] for item in items if item[0] == "USD")
    assert usd_share == Decimal("100.000")


def test_breakdown_limit_applies_per_currency(client: TestClient) -> None:
    _import_analytics(client)

    body = client.get(
        "/api/costs/breakdown", params={"dimension": "service", "limit": 1}
    ).json()
    assert [(item["currency"], item["key"]) for item in body["items"]] == [
        ("EUR", "SQL"),
        ("USD", "EC2"),
    ]
    assert body["total_groups"] == 4
    assert body["items_truncated"] is True


def test_breakdown_dimensions_and_filters(client: TestClient) -> None:
    _import_analytics(client)

    by_project = client.get(
        "/api/costs/breakdown", params={"dimension": "project", "currency": "USD"}
    ).json()
    assert [(item["key"], Decimal(item["amount"])) for item in by_project["items"]] == [
        ("proj-alpha", Decimal("17.500000")),
        ("proj-beta", Decimal("7.250000")),
    ]

    by_environment = client.get(
        "/api/costs/breakdown", params={"dimension": "environment", "project": "proj-alpha"}
    ).json()
    assert [(item["key"], Decimal(item["amount"])) for item in by_environment["items"]] == [
        ("prod", Decimal("15.000000")),
        ("dev", Decimal("2.500000")),
    ]

    by_provider = client.get("/api/costs/breakdown", params={"dimension": "provider"}).json()
    assert [(item["key"], item["currency"]) for item in by_provider["items"]] == [
        ("azure", "EUR"),
        ("aws", "USD"),
        ("gcp", "USD"),
    ]

    by_resource = client.get(
        "/api/costs/breakdown", params={"dimension": "resource", "limit": 1}
    ).json()
    assert [(item["key"], item["currency"]) for item in by_resource["items"]] == [
        ("rds-004", "EUR"),
        ("i-001", "USD"),
    ]


def test_daily_and_monthly_trends(client: TestClient) -> None:
    _import_analytics(client)

    daily = client.get("/api/costs/trends", params={"granularity": "day"}).json()
    assert [(p["bucket"], p["currency"], Decimal(p["amount"])) for p in daily["points"]] == [
        ("2026-01-01", "USD", Decimal("15.000000")),
        ("2026-01-02", "EUR", Decimal("4.000000")),
        ("2026-01-02", "USD", Decimal("2.500000")),
        ("2026-02-03", "USD", Decimal("7.250000")),
    ]
    assert _amounts(daily) == {"EUR": Decimal("4.000000"), "USD": Decimal("24.750000")}

    monthly = client.get("/api/costs/trends", params={"granularity": "month"}).json()
    assert [(p["bucket"], p["currency"], Decimal(p["amount"])) for p in monthly["points"]] == [
        ("2026-01", "EUR", Decimal("4.000000")),
        ("2026-01", "USD", Decimal("17.500000")),
        ("2026-02", "USD", Decimal("7.250000")),
    ]


def test_date_window_is_inclusive(client: TestClient) -> None:
    _import_analytics(client)

    body = client.get(
        "/api/costs/summary", params={"start": "2026-01-02", "end": "2026-01-02"}
    ).json()
    assert _amounts(body) == {"EUR": Decimal("4.000000"), "USD": Decimal("2.500000")}
    assert body["window"] == {"start": "2026-01-02", "end": "2026-01-02", "days": 1}


def test_invalid_date_range_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/costs/summary", params={"start": "2026-02-01", "end": "2026-01-01"}
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_date_range"
    assert error["details"] == {"start": "2026-02-01", "end": "2026-01-01"}


def test_empty_result_is_not_an_error(client: TestClient) -> None:
    _import_analytics(client)

    body = client.get("/api/costs/summary", params={"start": "2030-01-01"}).json()
    assert body["totals"] == []
    assert body["row_count"] == 0
    assert any("No billing rows" in note for note in body["notes"])


def test_reimported_rows_are_stored_but_excluded_from_totals(client: TestClient) -> None:
    first = _import_analytics(client).json()
    second = _import_analytics(client, force=True).json()
    assert second["status"] == "valid_with_warnings"
    assert second["id"] != first["id"]
    duplicate_warnings = [
        issue for issue in second["issues"] if issue["code"] == "duplicate_existing_record"
    ]
    assert len(duplicate_warnings) == 5

    body = client.get("/api/costs/summary").json()
    assert _amounts(body) == {"EUR": Decimal("4.000000"), "USD": Decimal("24.750000")}
    assert body["row_count"] == 5
    assert body["excluded_duplicate_rows"] == 5
    assert body["import_ids"] == [first["id"]]
    assert any("excluded from these totals" in note for note in body["notes"])

    # The duplicates remain visible for audit on the second import.
    records = client.get(f"/api/imports/{second['id']}/records", params={"limit": 1}).json()
    assert records["total"] == 5
