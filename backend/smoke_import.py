"""Smoke test for CSV ingestion, dataset status, reset, and the grounded assistant.

Runs against an isolated temporary database so it never touches the real one.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEMP_DB = Path(tempfile.gettempdir()) / "cloudpilot-import-smoke.db"
if TEMP_DB.exists():
    TEMP_DB.unlink()
os.environ["CLOUDPILOT_DB"] = str(TEMP_DB)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
checks = []


def check(name, condition, extra=""):
    checks.append((name, bool(condition), extra))


BILLING_CSV = """invoice_date,provider,service,project,region,environment,resource_id,amount,currency
2026-11-01,AWS,Amazon EC2,platform,us-east-1,production,i-1,10.50,USD
2026-11-02,AWS,Amazon S3,platform,us-east-1,production,b-1,20.25,USD
2026-11-03,Azure,Azure SQL,payments,eastus,production,db-1,30.00,USD
2026-11-04,AWS,Amazon EC2,platform,us-east-1,production,i-2,not-a-number,USD
2026-11-05,AWS,Lambda,platform,eu-west-1,production,f-1,9.99,GBP
"""

RESOURCES_CSV = """resource_id,name,resource_type,provider,environment,region,currency,cost_per_hour,cpu_pct,memory_pct,sku
r-new-01,batch-worker,ec2,AWS,production,us-east-1,USD,0.20,4,30,m5.large
r-new-02,api-eu,vm,Azure,production,westeurope,EUR,0.30,30,55,Standard_B2s
"""

# --- demo baseline -------------------------------------------------------- #
status = client.get("/api/data/status").json()
check("status mode demo", status["mode"] == "demo", status.get("mode"))
check("status three currencies", {c["currency"] for c in status["currencies"]} == {"USD", "EUR", "INR"}, str([c["currency"] for c in status["currencies"]]))

# --- templates ------------------------------------------------------------ #
tpl = client.get("/api/imports/template?dataset=billing")
check("billing template", tpl.status_code == 200 and "invoice_date" in tpl.text and tpl.headers["content-type"].startswith("text/csv"), str(tpl.status_code))
rtpl = client.get("/api/imports/template?dataset=resources")
check("resources template", rtpl.status_code == 200 and "cost_per_hour" in rtpl.text, str(rtpl.status_code))

# --- billing import (replace) --------------------------------------------- #
resp = client.post(
    "/api/imports/billing",
    json={"filename": "mine.csv", "content": BILLING_CSV, "mode": "replace"},
)
report = resp.json()
check("billing import ok", resp.status_code == 200 and report["ok"] is True, str(report.get("message")))
check("billing accepted 3", report["accepted"] == 3, str(report.get("accepted")))
check("billing rejected 2", report["rejected"] == 2, str(report.get("rejected")))
check("billing reports bad currency", any("GBP" in e["message"] for e in report["errors"]), str(report.get("errors")))
check("billing reports bad amount", any("amount" in e["message"] for e in report["errors"]), str(report.get("errors")))

summary = client.get("/api/summary?currency=USD").json()
check("replace reflects imported total", summary["total_spend"] == "60.75", summary.get("total_spend"))
check("replace removed demo USD rows", summary["row_count"] == 3, str(summary.get("row_count")))
eur = client.get("/api/summary?currency=EUR").json()
check("replace cleared other currencies", eur["row_count"] == 0, str(eur.get("row_count")))

status = client.get("/api/data/status").json()
check("status mode imported", status["mode"] == "imported", status.get("mode"))
check("status marks USD uploaded", any(c["currency"] == "USD" and c["origin"] == "uploaded" for c in status["currencies"]), str(status["currencies"]))
filters = client.get("/api/filters").json()
check("filters report imported source", filters["data_source"] == "imported", filters.get("data_source"))

# --- append ---------------------------------------------------------------- #
append_csv = """invoice_date,provider,service,amount,currency
2026-11-06,AWS,Amazon EC2,5.00,USD
"""
report = client.post(
    "/api/imports/billing",
    json={"filename": "append.csv", "content": append_csv, "mode": "append"},
).json()
check("append accepted 1", report["ok"] and report["accepted"] == 1, str(report.get("message")))
summary = client.get("/api/summary?currency=USD").json()
check("append keeps prior rows", summary["row_count"] == 4 and summary["total_spend"] == "65.75", f"{summary['row_count']} / {summary['total_spend']}")

# --- invalid files --------------------------------------------------------- #
bad = client.post(
    "/api/imports/billing",
    json={"filename": "bad.csv", "content": "invoice_date,provider\n2026-11-01,AWS\n", "mode": "replace"},
)
check("missing columns rejected", bad.status_code == 400, str(bad.status_code))

zero = client.post(
    "/api/imports/billing",
    json={
        "filename": "all-bad.csv",
        "content": "invoice_date,provider,service,amount,currency\n2026-11-01,AWS,EC2,nope,USD\n",
        "mode": "append",
    },
).json()
check("all-invalid rows not written", zero["ok"] is False and zero["accepted"] == 0, str(zero.get("message")))

# --- resources + generated findings --------------------------------------- #
resp = client.post(
    "/api/imports/resources",
    json={"filename": "inventory.csv", "content": RESOURCES_CSV, "mode": "replace"},
)
report = resp.json()
check("resources import ok", resp.status_code == 200 and report["ok"] is True, str(report.get("message")))
check("findings generated", report.get("findings_generated", 0) >= 2, str(report.get("findings_generated")))

usd_findings = client.get("/api/findings?currency=USD").json()["findings"]
check("USD finding for imported resource", any(f["resource_id"] == "r-new-01" for f in usd_findings), str([f["resource_id"] for f in usd_findings]))
eur_findings = client.get("/api/findings?currency=EUR").json()["findings"]
check("EUR finding for imported resource", any(f["resource_id"] == "r-new-02" for f in eur_findings), str([f["resource_id"] for f in eur_findings]))

# --- assistant ------------------------------------------------------------- #
def ask(question, currency="USD"):
    return client.post("/api/assistant/ask", json={"question": question, "currency": currency}).json()


answer = ask("What did we spend in USD?")
check("assistant total intent", answer["intent"] == "total_spend", answer["intent"])
check("assistant total grounded", "65.75" in answer["answer"], answer["answer"][:160])
check("assistant cites source", any("billing" in s for s in answer["sources"]), str(answer["sources"]))

answer = ask("What are the top services by cost?")
check("assistant top services", answer["intent"] == "top_services" and "Amazon EC2" in answer["answer"], answer["answer"][:160])

answer = ask("Tell me about r-new-01")
check("assistant resource lookup", answer["intent"] == "resource_lookup" and "r-new-01" in answer["answer"], answer["intent"])

answer = ask("Can I delete r-new-01?")
check("assistant policy blocks delete", answer["intent"] == "policy" and "blocked" in answer["answer"].lower(), answer["answer"][:160])

answer = ask("How do I import my own data?")
check("assistant import help", answer["intent"] == "how_to_import", answer["intent"])

answer = ask("What is the weather in Paris?")
check("assistant refuses unknown", answer["intent"] == "unsupported" and answer["confidence"] == "low", answer["intent"])

answer = ask("Is the data stale?")
check("assistant dataset intent", answer["intent"] == "dataset", answer["intent"])

answer = ask("Show me the findings and their baseline cost.")
check("assistant plural findings intent", answer["intent"] == "findings", answer["intent"])

answer = ask("Are there any anomalies right now?")
check("assistant anomalies intent", answer["intent"] == "anomalies", answer["intent"])

answer = ask("Why is my bill high?")
check("assistant cost driver intent", answer["intent"] == "cost_drivers", answer["intent"])
check("assistant cost driver names a service", "Amazon EC2" in answer["answer"], answer["answer"][:160])

answer = ask("Which resource should I stop?")
check("assistant recommends from findings", answer["intent"] == "findings", answer["intent"])

# --- third-party export shapes (header aliases) ----------------------------- #
alias_csv = """usage_date,provider,service,project,region,environment,cost_amount,currency
2026-11-10,AWS,Amazon RDS,platform,us-east-1,production,12.00,USD
"""
report = client.post(
    "/api/imports/billing",
    json={"filename": "cloudability.csv", "content": alias_csv, "mode": "append"},
).json()
check("alias billing import", report["ok"] and report["accepted"] == 1, str(report.get("errors")))

util_csv = """timestamp,resource_id,cpu_avg_pct,memory_avg_pct
2026-11-26,i-alias-1,3,40
2026-11-26,i-alias-2,70,60
"""
resp = client.post(
    "/api/imports/resources",
    json={"filename": "utilization.csv", "content": util_csv, "mode": "append", "currency": "INR"},
)
report = resp.json()
check(
    "utilization-only resource import",
    resp.status_code == 200 and report["ok"] and report["accepted"] == 2,
    str(report.get("errors")),
)
check(
    "utilization import warns about missing cost",
    any("cost" in w.lower() for w in report["warnings"]),
    str(report.get("warnings")),
)
check("default currency applied", "INR" in report["currencies"], str(report.get("currencies")))
inr_findings = client.get("/api/findings?currency=INR").json()["findings"]
check(
    "alias resource generated finding",
    any(f["resource_id"] == "i-alias-1" for f in inr_findings),
    str([f["resource_id"] for f in inr_findings]),
)

# --- reset ----------------------------------------------------------------- #
reset = client.post("/api/data/reset").json()
check("reset without body restores demo", reset["ok"] and reset["status"]["mode"] == "demo", str(reset.get("status", {}).get("mode")))
summary = client.get("/api/summary?currency=USD").json()
check("demo total restored", summary["total_spend"] == "32524.32", summary.get("total_spend"))

# --- report ---------------------------------------------------------------- #
passed = sum(1 for _, ok, _ in checks if ok)
total = len(checks)
print(f"\nIMPORT + ASSISTANT SMOKE: {passed}/{total} passed\n")
for name, ok, extra in checks:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({extra})" if not ok and extra else ""))

if TEMP_DB.exists():
    TEMP_DB.unlink()

raise SystemExit(0 if passed == total else 1)
