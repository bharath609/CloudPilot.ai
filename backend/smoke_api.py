"""End-to-end API smoke test using FastAPI's TestClient (no server needed)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
checks = []


def check(name, cond, extra=""):
    checks.append((name, bool(cond), extra))


# Basic endpoints
r = client.get("/api/health")
check("health", r.status_code == 200 and r.json()["status"] == "ok", str(r.status_code))

r = client.get("/api/filters")
j = r.json()
check("filters currencies", set(j["currencies"]) == {"USD", "EUR", "INR"}, str(j["currencies"]))
check("filters freshness", "freshness" in j and "data_age_hours" in j["freshness"], str(j.get("freshness")))

for cur in ("USD", "EUR", "INR"):
    r = client.get(f"/api/summary?currency={cur}")
    j = r.json()
    check(f"summary {cur}", r.status_code == 200 and float(j["total_spend"]) > 0, j.get("total_spend"))

    r = client.get(f"/api/costs?currency={cur}&granularity=daily")
    check(f"costs {cur}", r.status_code == 200 and len(r.json()["series"]) >= 60, str(len(r.json().get("series", []))))

    r = client.get(f"/api/findings?currency={cur}")
    check(f"findings {cur}", r.status_code == 200 and len(r.json()["findings"]) >= 2, str(len(r.json().get("findings", []))))

    r = client.get(f"/api/forecasts?currency={cur}")
    check(f"forecasts {cur}", r.status_code == 200 and len(r.json()["forecast"]) == 14, str(len(r.json().get("forecast", []))))

r = client.get("/api/resources?currency=USD")
check("resources USD", r.status_code == 200 and len(r.json()["resources"]) == 4, str(len(r.json().get("resources", []))))

r = client.get("/api/imports")
check("imports", r.status_code == 200 and len(r.json()["imports"]) == 3, str(len(r.json().get("imports", []))))

# Decision write
r = client.post("/api/findings/f-usd-1/decisions", json={"decision": "accept", "note": "approved in smoke", "reviewer": "ci"})
check("decision write", r.status_code == 200 and r.json()["ok"], str(r.status_code))
r = client.get("/api/audit")
check("audit has decision", any(d["finding_id"] == "f-usd-1" for d in r.json()["decisions"]))

# Layer endpoints
r = client.post("/api/v1/anomalies/spending", json={"currency": "USD"})
check("anomaly spending", r.status_code == 200 and "detected" in r.json(), str(r.status_code))

r = client.post("/api/v1/anomalies/capacity", json={"resource_id": "r-ec2-001"})
check("anomaly capacity", r.status_code == 200 and r.json()["kind"] == "capacity", str(r.status_code))

r = client.post("/api/v1/anomalies/performance", json={"resource_id": "r-ec2-002"})
check("anomaly performance", r.status_code == 200 and r.json()["kind"] == "performance", str(r.status_code))

r = client.post("/api/v1/policies/evaluate", json={"action_type": "delete_resource", "resource_id": "r-ec2-001", "environment": "production"})
check("policy blocks delete", r.status_code == 200 and r.json()["allowed"] is False, str(r.json()))

r = client.post("/api/v1/policies/evaluate", json={"action_type": "stop_resource", "resource_id": "r-ec2-001", "environment": "production"})
check("policy stop requires approval", r.status_code == 200 and r.json()["requires_approval"] is True, str(r.json()))

r = client.post("/api/v1/twin/simulate", json={"resource_id": "r-ec2-001", "scenario": "stop", "utilization_retention": 0})
check("twin simulate stop", r.status_code == 200 and r.json()["currency"] == "USD" and r.json()["production_isolated"] is True, str(r.status_code))

r = client.post("/api/v1/twin/simulate", json={"resource_id": "r-ec2-eu-01", "scenario": "rightsize", "sku_ratio": 0.5})
check("twin simulate EUR", r.status_code == 200 and r.json()["currency"] == "EUR", str(r.status_code))

r = client.post("/api/v1/investigation/start", json={"finding_id": "f-usd-1"})
j = r.json()
check("investigation", r.status_code == 200 and len(j["steps"]) == 8 and j["status"] == "complete", j.get("status"))

r = client.post("/api/v1/verification/run", json={"action_id": "a1", "resource_id": "r-ec2-001", "expected": {"state": "stopped", "cost": 0}, "observed": {"state": "stopped", "cost": 0}})
check("verification passed", r.status_code == 200 and r.json()["overall_status"] == "passed", str(r.json()))

# Report
passed = sum(1 for _, ok, _ in checks if ok)
total = len(checks)
print(f"\nAPI SMOKE: {passed}/{total} passed\n")
for name, ok, extra in checks:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({extra})" if not ok and extra else ""))

raise SystemExit(0 if passed == total else 1)
