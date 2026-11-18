"""Human review decisions: append-only history, sanitization and lookup."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
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
    response = client.post("/api/analysis/run", json={})
    assert response.status_code == 200, response.text
    return response.json()


def _decide(
    client: TestClient,
    finding_id: int,
    decision: str = "approve",
    *,
    actor: str = "reviewer@example.test",
    note: str | None = "Owner confirmed the workload is unused.",
):
    return client.post(
        f"/api/findings/{finding_id}/decision",
        json={"decision": decision, "actor": actor, "note": note},
    )


def test_decisions_require_an_existing_finding(client: TestClient) -> None:
    response = _decide(client, 999_999)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_decision_is_appended_and_latest_wins(client: TestClient, settings: Settings) -> None:
    data = _prepare(client, settings)
    finding = data["findings"][0]
    finding_id = finding["id"]
    before = client.get(f"/api/findings/{finding_id}").json()

    first = _decide(client, finding_id, "approve", actor="alice", note="Looks safe.")
    assert first.status_code == 201, first.text
    approved = first.json()
    assert approved["finding_id"] == finding_id
    assert approved["decision"] == "approve"
    assert approved["actor"] == "alice"
    assert approved["note"] == "Looks safe."

    second = _decide(client, finding_id, "reject", actor="bob", note=None)
    assert second.status_code == 201, second.text

    detail = client.get(f"/api/findings/{finding_id}").json()
    assert detail["decision"]["decision"] == "reject"
    assert detail["decision"]["actor"] == "bob"
    assert detail["decision"]["note"] is None

    history = client.get("/api/decisions", params={"finding_id": finding_id})
    assert history.status_code == 200
    payload = history.json()
    assert payload["total"] == 2
    assert [item["decision"] for item in payload["items"]] == ["reject", "approve"]
    assert payload["items"][0]["resource_id"] == finding["resource_id"]
    assert payload["items"][0]["estimated_monthly_savings"] == finding["estimated_monthly_savings"]

    after = client.get(f"/api/findings/{finding_id}").json()
    for field in (
        "estimated_monthly_savings",
        "baseline_monthly_cost",
        "proposed_monthly_cost",
        "confidence",
        "risk",
        "evidence",
    ):
        assert after[field] == before[field]


def test_decision_text_is_sanitized(client: TestClient, settings: Settings) -> None:
    data = _prepare(client, settings)
    finding_id = data["findings"][0]["id"]
    response = _decide(
        client,
        finding_id,
        actor="  Jane\nDoe\x00 ",
        note="line one\r\nline two\tend",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["actor"] == "Jane Doe"
    assert body["note"] == "line one line two end"


def test_blank_actor_is_rejected(client: TestClient, settings: Settings) -> None:
    data = _prepare(client, settings)
    finding_id = data["findings"][0]["id"]
    response = _decide(client, finding_id, actor="   ")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_actor"


@pytest.mark.parametrize("decision", ["approved", "ignore", ""])
def test_unknown_decision_value_is_rejected(
    client: TestClient, settings: Settings, decision: str
) -> None:
    data = _prepare(client, settings)
    finding_id = data["findings"][0]["id"]
    response = _decide(client, finding_id, decision)
    assert response.status_code == 422


def test_unknown_fields_are_rejected(client: TestClient, settings: Settings) -> None:
    data = _prepare(client, settings)
    finding_id = data["findings"][0]["id"]
    response = client.post(
        f"/api/findings/{finding_id}/decision",
        json={"decision": "approve", "actor": "alice", "apply_now": True},
    )
    assert response.status_code == 422


def test_decisions_can_be_filtered_by_kind(client: TestClient, settings: Settings) -> None:
    data = _prepare(client, settings)
    ids = [item["id"] for item in data["findings"]]
    assert len(ids) >= 2
    _decide(client, ids[0], "approve")
    _decide(client, ids[1], "needs_owner_review")

    approved = client.get("/api/decisions", params={"decision": "approve"}).json()
    assert approved["total"] == 1
    assert approved["items"][0]["finding_id"] == ids[0]

    pending = client.get("/api/decisions", params={"decision": "needs_owner_review"}).json()
    assert pending["total"] == 1
    assert pending["items"][0]["finding_id"] == ids[1]

    rejected = client.get("/api/decisions", params={"decision": "reject"}).json()
    assert rejected["total"] == 0


def test_findings_list_includes_latest_decision(client: TestClient, settings: Settings) -> None:
    data = _prepare(client, settings)
    finding_id = data["findings"][0]["id"]
    _decide(client, finding_id, "needs_owner_review", note="Ping the platform team.")

    listing = client.get("/api/findings").json()
    matching = [item for item in listing["items"] if item["id"] == finding_id]
    assert len(matching) == 1
    assert matching[0]["decision"]["decision"] == "needs_owner_review"
    assert matching[0]["decision"]["note"] == "Ping the platform team."
    others = [item for item in listing["items"] if item["id"] != finding_id]
    assert all(item["decision"] is None for item in others)
