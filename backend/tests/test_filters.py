"""Filter discovery and data freshness."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import ImportRecord, PriceEntry
from tests.conftest import import_billing_sample, import_utilization_sample


def test_empty_state_is_explicit(client: TestClient) -> None:
    response = client.get("/api/filters")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["import_count"] == 0
    assert body["window_start"] is None
    assert body["currencies"] == []
    assert body["contains_sample_data"] is False
    assert body["synthetic_price_count"] == 0
    assert any("No imports yet" in note for note in body["notes"])


def test_filter_values_come_from_stored_rows(client: TestClient) -> None:
    import_billing_sample(client)
    import_utilization_sample(client)

    body = client.get("/api/filters").json()
    assert body["window_start"] == "2026-01-01"
    assert body["window_end"] == "2026-03-01"
    assert body["day_count"] == 60
    assert body["currencies"] == ["USD"]
    assert body["providers"] == ["aws", "azure", "gcp"]
    assert "Amazon EC2" in body["services"]
    assert body["environments"] == ["dev", "prod", "staging"]
    assert "checkout-platform" in body["projects"]
    assert body["accounts"]
    assert all(not account.isdigit() for account in body["accounts"])
    assert body["import_count"] == 2
    assert body["last_import_at"] is not None
    assert body["last_import_filename"] == "utilization_sample.csv"
    assert body["last_billing_date"] == "2026-03-01"
    # API uploads are not marked as the seed source.
    assert body["contains_sample_data"] is False


def test_seed_source_and_synthetic_prices_are_flagged(client: TestClient) -> None:
    import_billing_sample(client)
    session = client.app.state.db.session_factory()
    try:
        for record in session.scalars(select(ImportRecord)):
            record.source = "sample"
        session.commit()

        session.add(
            PriceEntry(
                provider="aws",
                sku="demo.test",
                display_name="Synthetic test price",
                service="Amazon EC2",
                region="eu-west-1",
                usage_unit="Hrs",
                unit_price="0.100000",
                currency="USD",
                effective_from=date(2025, 1, 1),
                is_synthetic=True,
                source_name="test",
                source_url="https://example.invalid/test",
            )
        )
        session.commit()
    finally:
        session.close()

    body = client.get("/api/filters").json()
    assert body["contains_sample_data"] is True
    assert body["synthetic_price_count"] == 1
    assert any("synthetic sample seed" in note for note in body["notes"])
    assert any("synthetic demo prices" in note for note in body["notes"])
