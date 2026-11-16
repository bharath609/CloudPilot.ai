"""Health and root endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_database_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["environment"] == "test"
    assert body["version"] == "0.1.0"


def test_short_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_root_points_to_docs(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"
