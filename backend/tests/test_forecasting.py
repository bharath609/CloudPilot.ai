"""Spend forecasting: exact values, held-out metrics, intervals and disclosures."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from tests.conftest import upload

HEADER = [
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
]


def _daily_csv(
    values: list[Decimal],
    *,
    start: date = date(2026, 1, 1),
    currency: str = "USD",
    service: str = "Amazon EC2",
    resource_id: str = "i-forecast-001",
    account_id: str = "demo-aws-account-001",
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(HEADER)
    for offset, value in enumerate(values):
        writer.writerow(
            [
                (start + timedelta(days=offset)).isoformat(),
                "aws",
                account_id,
                service,
                resource_id,
                "eu-west-1",
                "dev",
                "sandbox",
                "24",
                "Hrs",
                f"{value:.6f}",
                currency,
                "platform",
                "platform@example.test",
            ]
        )
    return buffer.getvalue().encode()


def _upload(client: TestClient, content: bytes, name: str = "forecast.csv") -> dict:
    response = upload(client, "billing", content, filename=name)
    assert response.status_code == 201, response.text
    return response.json()


def _series(body: dict, currency: str = "USD") -> dict:
    return next(item for item in body["series"] if item["currency"] == currency)


def test_seasonal_naive_is_exact_on_a_repeating_week(client: TestClient) -> None:
    # Four identical weeks: 1,2,3,4,5,6,7.
    values = [Decimal((offset % 7) + 1) for offset in range(28)]
    _upload(client, _daily_csv(values))

    response = client.post("/api/forecasts/run", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    run = body["run"]
    assert run["method"] == "seasonal_naive"
    assert run["granularity"] == "day"
    assert run["series_count"] == 1
    assert run["reference_date"] == "2026-01-28"
    assert run["history_start"] == "2026-01-01"
    assert run["history_end"] == "2026-01-28"
    assert run["horizon_start"] == "2026-01-29"
    assert run["horizon_end"] == "2026-02-27"

    series = _series(body)
    assert series["history_days"] == 28
    assert series["evaluation"]["train_days"] == 14
    assert series["evaluation"]["holdout_days"] == 14
    assert series["evaluation"]["evaluated_points"] == 14
    assert series["evaluation"]["mae"] == "0.000000"
    assert series["evaluation"]["rmse"] == "0.000000"
    assert series["evaluation"]["bias"] == "0.000000"
    assert series["evaluation"]["mape_pct"] == "0.000"
    assert series["evaluation"]["interval_width"] == "0.000000"
    assert series["evaluation"]["confidence"] == "low"

    # 30 future days = four complete weeks (112) plus 1 and 2.
    assert series["projected_total"] == "115.000000"
    assert series["projected_lower"] == "115.000000"
    assert series["projected_upper"] == "115.000000"
    assert len(series["points"]) == 30
    assert series["points"][0] == {
        "period": "2026-01-29",
        "predicted_cost": "1.000000",
        "lower_bound": "1.000000",
        "upper_bound": "1.000000",
    }
    assert [Decimal(point["predicted_cost"]) for point in series["points"][:7]] == [
        Decimal(value) for value in range(1, 8)
    ]
    assert any("degenerate" in warning for warning in series["evaluation"]["warnings"])
    assert any("Only 28 days" in warning for warning in series["evaluation"]["warnings"])
    assert any("no AI" in note for note in run["notes"])


def test_moving_average_metrics_are_hand_calculated(client: TestClient) -> None:
    values = [Decimal((offset % 7) + 1) for offset in range(28)]
    _upload(client, _daily_csv(values))

    response = client.post(
        "/api/forecasts/run",
        json={
            "method": "moving_average",
            "moving_average_days": 7,
            "holdout_days": 14,
            "horizon_days": 7,
        },
    )
    assert response.status_code == 200, response.text
    series = _series(response.json())
    evaluation = series["evaluation"]

    # Train is two weeks; the last seven values average to 4.
    assert evaluation["mae"] == "1.714286"  # 12/7
    assert evaluation["rmse"] == "2.000000"  # sqrt(56/14)
    assert evaluation["bias"] == "0.000000"
    assert evaluation["mape_pct"] == "75.646"
    assert evaluation["mape_excluded_points"] == 0
    assert evaluation["interval_width"] == "3.000000"  # 90th percentile of |errors|
    assert series["projected_total"] == "28.000000"
    assert series["projected_lower"] == "7.000000"
    assert series["projected_upper"] == "49.000000"
    assert {point["predicted_cost"] for point in series["points"]} == {"4.000000"}
    assert any("flat forecast" in warning for warning in evaluation["warnings"])


def test_currencies_are_forecast_separately(client: TestClient) -> None:
    values = [Decimal((offset % 7) + 1) for offset in range(28)]
    _upload(client, _daily_csv(values, currency="USD", resource_id="i-usd"))
    _upload(
        client,
        _daily_csv(
            [value * 2 for value in values],
            currency="EUR",
            resource_id="vm-eur",
            account_id="demo-azure-001",
            service="Virtual Machines",
        ),
        name="eur.csv",
    )

    body = client.post("/api/forecasts/run", json={"horizon_days": 7}).json()
    assert body["run"]["series_count"] == 2
    assert {item["currency"] for item in body["series"]} == {"EUR", "USD"}
    assert _series(body, "USD")["projected_total"] == "28.000000"
    assert _series(body, "EUR")["projected_total"] == "56.000000"
    assert body["run"]["stats"]["contains_sample_data"] is False
    assert any("not be added together" in note for note in body["run"]["notes"])
    assert "total" not in body


def test_filters_restrict_the_forecast_scope(client: TestClient) -> None:
    cheap = [Decimal(1) for _ in range(28)]
    expensive = [Decimal(10) for _ in range(28)]
    _upload(client, _daily_csv(cheap, service="Amazon S3", resource_id="bucket-a"))
    _upload(
        client,
        _daily_csv(expensive, service="Amazon EC2", resource_id="i-b"),
        name="ec2.csv",
    )

    body = client.post(
        "/api/forecasts/run", json={"service": "Amazon S3", "horizon_days": 7}
    ).json()
    assert body["run"]["filters"]["service"] == "Amazon S3"
    assert body["run"]["series_count"] == 1
    assert _series(body)["projected_total"] == "7.000000"


def test_insufficient_history_is_rejected_with_details(client: TestClient) -> None:
    _upload(client, _daily_csv([Decimal(5) for _ in range(10)]))
    response = client.post("/api/forecasts/run", json={})
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "insufficient_history"
    assert error["details"]["min_history_days"] == 28
    assert error["details"]["skipped"] == {"USD": "insufficient_history"}


def test_no_billing_and_empty_history_are_explicit(client: TestClient) -> None:
    empty = client.get("/api/forecasts")
    assert empty.status_code == 200
    assert empty.json() == {"run": None, "series": [], "total": 0}

    response = client.post("/api/forecasts/run", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_billing_data"


def test_zero_spend_holdout_excludes_mape_and_discloses_it(client: TestClient) -> None:
    values = [Decimal(5) for _ in range(14)] + [Decimal(0) for _ in range(14)]
    _upload(client, _daily_csv(values))

    body = client.post("/api/forecasts/run", json={}).json()
    series = _series(body)
    assert series["evaluation"]["mape_pct"] is None
    assert series["evaluation"]["mape_excluded_points"] == 14
    # The model repeats the last known weekday value (5) into the all-zero tail.
    assert series["evaluation"]["mae"] == "5.000000"
    assert series["evaluation"]["bias"] == "-5.000000"
    assert series["evaluation"]["interval_width"] == "5.000000"
    assert any("MAPE is unavailable" in warning for warning in series["evaluation"]["warnings"])


def test_runs_are_reproducible_and_old_runs_remain_queryable(client: TestClient) -> None:
    values = [Decimal((offset % 7) + 1) for offset in range(28)]
    _upload(client, _daily_csv(values))

    first = client.post("/api/forecasts/run", json={"horizon_days": 7}).json()
    second = client.post("/api/forecasts/run", json={"horizon_days": 7}).json()
    assert first["run"]["id"] != second["run"]["id"]
    assert first["series"][0]["projected_total"] == second["series"][0]["projected_total"]
    assert [
        (point["period"], point["predicted_cost"]) for point in first["series"][0]["points"]
    ] == [
        (point["period"], point["predicted_cost"]) for point in second["series"][0]["points"]
    ]

    latest = client.get("/api/forecasts").json()
    assert latest["run"]["id"] == second["run"]["id"]
    older = client.get("/api/forecasts", params={"run_id": first["run"]["id"]}).json()
    assert older["run"]["id"] == first["run"]["id"]
    assert older["series"][0]["projected_total"] == first["series"][0]["projected_total"]

    detail = client.get(f"/api/forecasts/{first['run']['id']}").json()
    assert detail["run"]["id"] == first["run"]["id"]
    assert len(detail["series"][0]["points"]) == 7
    assert client.get("/api/forecasts/999999").status_code == 404
