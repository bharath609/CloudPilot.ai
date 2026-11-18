"""Server-side exports: sanitization, currency separation and content."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.models import Finding
from app.services.exports import _markdown, _text
from app.services.prices import load_price_catalogue, resolve_catalogue_path
from tests.conftest import import_billing_sample, import_utilization_sample


def _prepare(client: TestClient, settings: Settings) -> dict:
    import_billing_sample(client)
    import_utilization_sample(client)
    session = client.app.state.db.session_factory()
    try:
        load_price_catalogue(session, resolve_catalogue_path(settings))
    finally:
        session.close()
    analysis = client.post("/api/analysis/run", json={})
    assert analysis.status_code == 200, analysis.text
    forecast = client.post("/api/forecasts/run", json={})
    assert forecast.status_code == 200, forecast.text
    return {"analysis": analysis.json(), "forecast": forecast.json()}


def _csv_rows(response) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(response.text))
    return list(reader)


def test_formula_prefixes_are_neutralized() -> None:
    assert _text("=HYPERLINK('http://evil')") == "'=HYPERLINK('http://evil')"
    assert _text("+1") == "'+1"
    assert _text("-cmd") == "'-cmd"
    assert _text("@SUM(A1)") == "'@SUM(A1)"
    assert _text("safe text") == "safe text"
    assert _text("line\r\nbreak") == "line  break"
    assert _markdown("a|b") == "a\\|b"


def test_findings_csv_is_excel_safe_and_complete(
    client: TestClient, settings: Settings
) -> None:
    data = _prepare(client, settings)
    response = client.get("/api/exports/findings.csv")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"

    rows = _csv_rows(response)
    findings = data["analysis"]["findings"]
    assert len(rows) == len(findings)
    by_id = {row["finding_id"]: row for row in rows}
    for finding in findings:
        row = by_id[f"finding-{finding['id']}"]
        assert row["run_id"] == str(finding["run_id"])
        assert row["currency"] == "USD"
        assert row["estimated_monthly_savings"] == finding["estimated_monthly_savings"]
        assert row["risk"] == finding["risk"]
        assert row["latest_decision"] == ""
        assert row["uses_synthetic_prices"] in {"true", "false"}


def test_hostile_cells_are_prefixed(client: TestClient, settings: Settings) -> None:
    data = _prepare(client, settings)
    finding_id = data["analysis"]["findings"][0]["id"]
    session = client.app.state.db.session_factory()
    try:
        finding = session.get(Finding, finding_id)
        finding.resource_id = "=cmd|' /C calc'!A0"
        finding.service = "+SUM(1,1)"
        session.commit()
    finally:
        session.close()

    response = client.get("/api/exports/findings.csv")
    rows = _csv_rows(response)
    row = next(item for item in rows if item["finding_id"] == f"finding-{finding_id}")
    assert row["resource_id"].startswith("'=")
    assert row["service"].startswith("'+")


def test_decisions_appear_in_csv_and_markdown(
    client: TestClient, settings: Settings
) -> None:
    data = _prepare(client, settings)
    finding_id = data["analysis"]["findings"][0]["id"]
    response = client.post(
        f"/api/findings/{finding_id}/decision",
        json={"decision": "approve", "actor": "alice", "note": "Confirmed with owner."},
    )
    assert response.status_code == 201, response.text

    rows = _csv_rows(client.get("/api/exports/findings.csv"))
    row = next(item for item in rows if item["finding_id"] == f"finding-{finding_id}")
    assert row["latest_decision"] == "approve"
    assert row["decision_actor"] == "alice"
    assert row["decision_note"] == "Confirmed with owner."
    assert datetime.fromisoformat(row["decision_at"]).tzinfo is not None

    report = client.get("/api/exports/summary.md")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/markdown")
    text = report.text
    assert "# CloudPilot AI - cost optimization report" in text
    assert "## Spend by currency" in text
    assert "| USD | 1531.305850 | 480 |" in text
    assert "## Findings" in text
    assert f"finding-{finding_id}" in text
    assert "approve by alice" in text
    assert "Confirmed with owner." in text
    assert "## Forecast" in text
    assert "765.016323" in text
    assert "## Data lineage" in text
    assert "billing_sample.csv" in text
    assert "Synthetic data: **yes" in text
    assert "No resource is stopped, resized or deleted" in text


def test_markdown_notes_synthetic_prices(client: TestClient, settings: Settings) -> None:
    _prepare(client, settings)
    text = client.get("/api/exports/summary.md").text
    assert "synthetic=True" in text
    assert "illustrative" in text or "demo prices" in text


def test_unknown_runs_are_not_found(client: TestClient, settings: Settings) -> None:
    _prepare(client, settings)
    csv_response = client.get("/api/exports/findings.csv", params={"run_id": 999_999})
    assert csv_response.status_code == 404
    md_response = client.get(
        "/api/exports/summary.md", params={"forecast_run_id": 999_999}
    )
    assert md_response.status_code == 404


def test_empty_database_exports_are_explicit(client: TestClient) -> None:
    csv_response = client.get("/api/exports/findings.csv")
    assert csv_response.status_code == 200
    assert _csv_rows(csv_response) == []

    md_response = client.get("/api/exports/summary.md")
    assert md_response.status_code == 200
    assert "_No analysis run or no findings._" in md_response.text
    assert "_No billing rows._" in md_response.text
    assert "_No forecast run stored._" in md_response.text
