"""End-to-end release smoke test for a running CloudPilot AI instance.

The test talks to a live API over HTTP only. It performs no cloud calls and it
writes only to the target application's own database (one decision row and one
deliberately invalid import at the very end).

Usage (from the repository root):

    python scripts/release_smoke_test.py
    $env:BASE_URL = "http://127.0.0.1:8000"; python scripts/release_smoke_test.py

The instance must already contain the synthetic sample import, for example:

    python scripts/seed_sample_data.py --database-url sqlite:///./cloudpilot.db

Exit code 0 means every check passed.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
EXPECTED_VERSION = "1.0.0"
FAILS: list[str] = []


def call(path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def get_json(path: str, method: str = "GET", body: dict | None = None):
    status, headers, raw = call(path, method, body)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        payload = None
    return status, headers, payload, raw


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" :: {detail}" if detail else ""))
    if not condition:
        FAILS.append(name)


def upload_csv(path: str, filename: str, content: bytes):
    boundary = "----cloudpilot" + uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: text/csv\r\n\r\n",
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(BASE + path, data=body, method="POST")
    request.add_header("Accept", "application/json")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def main() -> int:
    # 1. Static frontend served from the API origin -----------------------
    status, headers, raw = call("/")
    html = raw.decode("utf-8", "replace")
    check("GET / serves the built SPA", status == 200 and 'id="root"' in html, f"HTTP {status}")
    check("SPA keeps the CloudPilot title", "CloudPilot AI" in html, headers.get("content-type", ""))

    assets = []
    for line in html.splitlines():
        if "/assets/" in line and ".js" in line:
            start = line.find("/assets/")
            end = line.find('"', start)
            assets.append(line[start:end])
    if assets:
        status, _, asset = call(assets[0])
        check("built JS asset is served", status == 200 and len(asset) > 1000, assets[0])
    else:
        check("built JS asset is referenced", False, "no /assets/ script in index.html")

    # 2. Health and filters ----------------------------------------------
    status, _, health, _ = get_json("/api/health")
    check(
        "API health is ok and reports v1.0.0",
        status == 200 and health.get("status") == "ok" and health.get("version") == EXPECTED_VERSION,
        f"v{health.get('version')}",
    )

    status, _, filters, _ = get_json("/api/filters")
    check(
        "filters show the sample import and 60-day window",
        status == 200
        and filters["import_count"] == 2
        and filters["contains_sample_data"] is True
        and filters["window_start"] == "2026-01-01"
        and filters["window_end"] == "2026-03-01"
        and filters["day_count"] == 60,
        f"{filters['window_start']}..{filters['window_end']} imports={filters['import_count']}",
    )
    check(
        "filters flag synthetic prices",
        filters["synthetic_price_count"] > 0,
        f"{filters['synthetic_price_count']} price(s)",
    )
    check(
        "currency list is exact and partitioned",
        filters["currencies"] == ["USD"],
        str(filters["currencies"]),
    )

    # 3. Cost summary and resource health ---------------------------------
    status, _, summary, _ = get_json("/api/costs/summary?currency=USD")
    total = summary["totals"][0]
    check(
        "summary total is exact",
        status == 200 and total["amount"] == "1531.305850" and total["row_count"] == 480,
        f"{total['amount']} {total['currency']}",
    )

    status, _, resources, _ = get_json("/api/resources?currency=USD&limit=10")
    idle = [item for item in resources["items"] if item["idle_candidate"]]
    check(
        "resource health lists four observed resources",
        status == 200 and resources["total"] == 4,
        f"total={resources['total']} window={resources['window']}",
    )
    check(
        "idle pre-check matches the sample resource",
        any(item["resource_id"] == "i-demo-0a1b2c3d4e60" for item in idle),
        f"{len(idle)} idle candidate(s)",
    )

    # 4. Analysis and decision workflow ------------------------------------
    status, _, analysis, _ = get_json("/api/analysis/run", "POST", {"currency": "USD"})
    findings = analysis["findings"] if analysis else []
    check(
        "analysis produces three findings",
        status == 200 and len(findings) == 3,
        f"HTTP {status}, {len(findings)} finding(s)",
    )
    savings = sorted(item["estimated_monthly_savings"] for item in findings)
    check(
        "finding savings are exact decimals and sum to the stored total",
        savings == ["138.563898", "68.957640", "69.198481"]
        and sum(Decimal(value) for value in savings) == Decimal("276.720019"),
        str(savings),
    )

    finding_id = findings[0]["id"]
    status, _, decision, _ = get_json(
        f"/api/findings/{finding_id}/decision",
        "POST",
        {
            "decision": "approve",
            "actor": "release-smoke-test",
            "note": "Verified by scripts/release_smoke_test.py.",
        },
    )
    check(
        "decision POST returns 201",
        status == 201 and decision["finding_id"] == finding_id,
        f"HTTP {status}",
    )

    status, _, listing, _ = get_json("/api/findings?currency=USD")
    latest = next(item for item in listing["items"] if item["id"] == finding_id)["decision"]
    check(
        "latest decision is shown on the finding",
        latest is not None
        and latest["decision"] == "approve"
        and latest["actor"] == "release-smoke-test",
        str(latest),
    )

    status, _, decisions, _ = get_json("/api/decisions")
    check(
        "audit history is append-only and queryable",
        status == 200 and decisions["total"] == 1 and decisions["items"][0]["note"].startswith("Verified"),
        f"total={decisions['total']}",
    )

    # 5. Forecast and advisor --------------------------------------------
    status, _, forecast, _ = get_json("/api/forecasts/run", "POST", {"currency": "USD"})
    series = forecast["series"][0] if forecast else {}
    evaluation = series.get("evaluation") or {}
    check(
        "forecast total matches the stored sample",
        status == 200 and series.get("projected_total") == "765.016323",
        str(series.get("projected_total")),
    )
    check(
        "forecast includes a held-out evaluation and interval",
        {"mae", "rmse", "bias", "mape_pct", "interval_quantile", "holdout_days", "confidence"}
        <= set(evaluation)
        and series.get("projected_lower") is not None
        and series.get("projected_upper") is not None,
        f"mae={evaluation.get('mae')} quantile={evaluation.get('interval_quantile')}",
    )

    status, _, report, _ = get_json("/api/reports/generate", "POST", {"include_forecast": True})
    check(
        "advisor falls back deterministically when disabled",
        status == 201
        and report["ai_used"] is False
        and report["mode"] == "deterministic"
        and report["fallback_reason"] == "disabled"
        and report["output"]["human_review_required"] is True,
        f"mode={report['mode']} fallback={report['fallback_reason']}",
    )
    evidence_ids = [
        evidence_id
        for item in report["output"].get("priority_findings", [])
        for evidence_id in item.get("evidence_ids", [])
    ]
    check(
        "advisor findings cite stored evidence IDs",
        bool(evidence_ids)
        and all(
            evidence_id.startswith(("cost-", "metric-", "finding-"))
            for evidence_id in evidence_ids
        ),
        f"{len(evidence_ids)} evidence reference(s)",
    )

    status, _, reports, _ = get_json("/api/reports")
    check(
        "advisor report is stored and listable",
        status == 200 and reports["total"] == 1,
        f"total={reports['total']}",
    )

    # The advisor is read-only: stored totals must be unchanged afterwards.
    status, _, summary_after, _ = get_json("/api/costs/summary?currency=USD")
    check(
        "advisor cannot modify calculated totals",
        status == 200 and summary_after["totals"][0]["amount"] == "1531.305850",
        summary_after["totals"][0]["amount"],
    )

    # 6. Exports ----------------------------------------------------------
    status, headers, raw = call("/api/exports/findings.csv")
    text = raw.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    check(
        "CSV export has one row per finding",
        status == 200 and len(rows) == 3,
        f"HTTP {status}, {len(rows)} row(s)",
    )
    check(
        "CSV includes the latest decision",
        any(
            row["latest_decision"] == "approve" and row["decision_actor"] == "release-smoke-test"
            for row in rows
        ),
        "decision columns",
    )
    check(
        "CSV is an attachment with nosniff",
        "attachment" in headers.get("content-disposition", "")
        and headers.get("x-content-type-options") == "nosniff",
        headers.get("content-disposition", ""),
    )

    status, headers, raw = call("/api/exports/summary.md")
    report_text = raw.decode("utf-8")
    check(
        "Markdown report contains totals, decisions, forecast and lineage",
        status == 200
        and "| USD | 1531.305850 | 480 |" in report_text
        and "approve by release-smoke-test" in report_text
        and "765.016323" in report_text
        and "## Data lineage" in report_text
        and "billing_sample.csv" in report_text,
        f"HTTP {status}, {len(report_text)} chars",
    )
    check(
        "Markdown report labels synthetic data and the no-action policy",
        "Synthetic data: **yes" in report_text
        and "No resource is stopped, resized or deleted" in report_text,
        "labels present",
    )

    # 7. Validation errors are useful ------------------------------------
    sample = REPO_ROOT / "data" / "sample" / "billing_missing_column.csv"
    status, _, raw = upload_csv("/api/imports/billing", sample.name, sample.read_bytes())
    payload = json.loads(raw.decode("utf-8"))
    issue = payload["issues"][0] if payload.get("issues") else {}
    check(
        "invalid CSV is recorded with a useful validation error",
        status == 201
        and payload["status"] == "invalid"
        and payload["accepted_row_count"] == 0
        and bool(issue.get("code"))
        and bool(issue.get("message")),
        f"status={payload.get('status')} issue={issue.get('code')}",
    )

    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s): {FAILS}")
        return 1
    print("All release checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
