"""CSV ingestion for user-provided billing and resource inventory data.

Every row is validated before it is written. Money keeps its original currency and is
stored as an exact decimal string; nothing is converted. Validation problems are returned
as a report instead of silently dropping rows.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from .config import ALLOWED_CURRENCIES
from .db import money, seed_db

MAX_CONTENT_BYTES = 25 * 1024 * 1024
MAX_REPORTED_ERRORS = 50

BILLING_REQUIRED = ["invoice_date", "provider", "service", "amount", "currency"]
BILLING_OPTIONAL_DEFAULTS = {
    "project": "imported",
    "region": "unknown",
    "environment": "production",
    "resource_id": "",
    "resource_type": "unknown",
    "usage_amount": "1",
    "unit": "unit",
    "unit_price": "",
    "sku": "",
}

# Only the resource identity is genuinely required: an export that tracks utilization
# without cost metadata is still useful for findings, and missing fields get explicit
# defaults plus a warning in the import report.
RESOURCE_REQUIRED = ["resource_id"]
RESOURCE_OPTIONAL_DEFAULTS = {
    "environment": "production",
    "region": "unknown",
    "cpu_pct": "0",
    "memory_pct": "0",
    "status": "",
    "sku": "",
}

# Exports use many different header names for the same concept. These are normalized at
# parse time so a CloudZero/AWS/Cloudability export works without hand editing.
HEADER_ALIASES = {
    "invoice_date": ("usage_date", "billing_date", "charge_date", "start_date", "date"),
    "amount": (
        "cost_amount", "cost", "unblended_cost", "blended_cost", "total_cost",
        "net_cost", "cost_usd", "amount_usd", "cost_amount_usd",
    ),
    "provider": ("cloud_provider", "vendor"),
    "service": ("service_name", "product", "product_name"),
    "currency": ("currency_code",),
    "project": ("project_name", "tag_project"),
    "region": ("region_name", "location"),
    "environment": ("env", "tag_environment"),
    "resource_type": ("instance_type", "type", "service_type"),
    "usage_amount": ("usage_quantity", "quantity", "usage_qty"),
    "unit": ("usage_unit", "uom"),
    "unit_price": ("unit_cost",),
    "name": ("resource_name", "instance_name"),
    "cost_per_hour": ("hourly_cost", "cost_rate", "cost_per_hour_usd"),
    "cpu_pct": ("cpu_avg_pct", "cpu_avg", "cpu"),
    "memory_pct": ("memory_avg_pct", "memory_avg", "memory"),
}
ALIAS_TO_CANONICAL = {
    alias: canonical for canonical, aliases in HEADER_ALIASES.items() for alias in aliases
}


class ImportRejected(ValueError):
    """Raised when a file cannot be used at all (bad header, empty, too large)."""


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _normalize_header(name: str) -> str:
    return name.replace("\ufeff", "").strip().lower().replace(" ", "_").replace("-", "_")


def _split_rows(content: str) -> Tuple[List[str], List[Tuple[int, Dict[str, str]]]]:
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise ImportRejected(
            f"File is larger than {MAX_CONTENT_BYTES // (1024 * 1024)} MB. Split it into smaller files."
        )
    text = content.replace("\ufeff", "").strip()
    if not text:
        raise ImportRejected("The file is empty.")

    first_line = text.splitlines()[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        raw_header = next(reader)
    except StopIteration:
        raise ImportRejected("The file has no header row.")

    header = [_normalize_header(h) for h in raw_header]
    # Rename known aliases to canonical names, but never shadow a canonical column that is
    # already present in the file.
    present = set(header)
    resolved: List[str] = []
    for name in header:
        canonical = ALIAS_TO_CANONICAL.get(name)
        resolved.append(canonical if canonical and canonical not in present else name)
    header = resolved
    rows: List[Tuple[int, Dict[str, str]]] = []
    for index, values in enumerate(reader, start=2):
        if not values or all(not v.strip() for v in values):
            continue
        record: Dict[str, str] = {}
        for i, key in enumerate(header):
            if not key:
                continue
            record[key] = values[i] if i < len(values) else ""
        rows.append((index, record))
    return header, rows


def _require_headers(header: List[str], required: List[str], dataset: str) -> None:
    missing = [c for c in required if c not in header]
    if missing:
        raise ImportRejected(
            f"Missing required column(s) for {dataset}: {', '.join(missing)}. "
            f"Found: {', '.join(h for h in header if h) or '(none)'}."
        )


def parse_date(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal(value: str) -> Optional[Decimal]:
    raw = (value or "").strip().replace(" ", "").replace("\u00a0", "")
    if not raw:
        return None
    for token in ("USD", "EUR", "INR", "$", "\u20ac", "\u20b9", "\u00a3"):
        raw = raw.replace(token, "")
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1]
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    elif "," in raw:
        if raw.count(",") == 1 and len(raw.split(",")[1]) == 2:
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    if abs(number) > Decimal("1000000000000"):
        return None
    return -number if negative else number


def _parse_float(value: str, fallback: float = 0.0) -> float:
    parsed = parse_decimal(value)
    return float(parsed) if parsed is not None else fallback


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_report(dataset: str, filename: str, mode: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "dataset": dataset,
        "filename": filename,
        "mode": mode,
        "accepted": 0,
        "rejected": 0,
        "currencies": {},
        "errors": [],
        "warnings": [],
        "message": "",
    }


def _add_error(report: Dict[str, Any], line: int, message: str) -> None:
    report["rejected"] += 1
    if len(report["errors"]) < MAX_REPORTED_ERRORS:
        report["errors"].append({"line": line, "message": message})


def _finish(report: Dict[str, Any], accepted: int, imported: List[str]) -> Dict[str, Any]:
    report["accepted"] = accepted
    report["ok"] = accepted > 0
    if accepted == 0:
        report["message"] = "No rows were imported. Fix the reported problems and try again."
    else:
        suffix = f" {report['rejected']} row(s) were rejected." if report["rejected"] else ""
        report["message"] = f"Imported {accepted} row(s) from {len(imported)} currency group(s).{suffix}"
    return report


# --------------------------------------------------------------------------- #
# Billing
# --------------------------------------------------------------------------- #
def import_billing(
    conn: sqlite3.Connection,
    filename: str,
    content: str,
    mode: str = "replace",
    source: str = "upload",
) -> Dict[str, Any]:
    if mode not in ("replace", "append"):
        raise ImportRejected("mode must be 'replace' or 'append'.")

    header, rows = _split_rows(content)
    _require_headers(header, BILLING_REQUIRED, "billing")

    report = _new_report("billing", filename, mode)
    prepared: Dict[str, List[tuple]] = {}

    for line, record in rows:
        currency = (record.get("currency") or "").strip().upper()
        if currency not in ALLOWED_CURRENCIES:
            _add_error(
                report, line,
                f"Unsupported currency '{record.get('currency', '')}'. "
                f"Supported: {', '.join(ALLOWED_CURRENCIES)}.",
            )
            continue

        invoice_date = parse_date(record.get("invoice_date", ""))
        if invoice_date is None:
            _add_error(report, line, "invoice_date must be YYYY-MM-DD.")
            continue

        amount = parse_decimal(record.get("amount", ""))
        if amount is None:
            _add_error(report, line, "amount must be a number (e.g. 1234.56).")
            continue

        provider = (record.get("provider") or "").strip()
        service = (record.get("service") or "").strip()
        if not provider or not service:
            _add_error(report, line, "provider and service are required.")
            continue

        usage = _parse_float(record.get("usage_amount", ""), 1.0)
        unit_price_raw = record.get("unit_price", "")
        unit_price = parse_decimal(unit_price_raw) if unit_price_raw.strip() else None
        if unit_price is None:
            unit_price = amount / Decimal(str(usage)) if usage else amount

        prepared.setdefault(currency, []).append(
            (
                invoice_date.isoformat(),
                provider,
                service,
                (record.get("project") or BILLING_OPTIONAL_DEFAULTS["project"]).strip(),
                (record.get("region") or BILLING_OPTIONAL_DEFAULTS["region"]).strip(),
                (record.get("environment") or BILLING_OPTIONAL_DEFAULTS["environment"]).strip(),
                (record.get("resource_id") or "").strip() or "unassigned",
                (record.get("resource_type") or BILLING_OPTIONAL_DEFAULTS["resource_type"]).strip(),
                usage,
                (record.get("unit") or BILLING_OPTIONAL_DEFAULTS["unit"]).strip(),
                money(unit_price),
                money(amount),
                currency,
                (record.get("sku") or "").strip(),
            )
        )

    total = sum(len(v) for v in prepared.values())
    if total == 0:
        _finish(report, 0, [])
        return report

    if mode == "replace":
        for table in ("decisions", "findings", "resources", "billing", "imports"):
            conn.execute(f"DELETE FROM {table}")

    imported: List[str] = []
    try:
        for currency, values in sorted(prepared.items()):
            cur = conn.execute(
                "INSERT INTO imports (filename, source, currency, row_count, imported_at, dataset) "
                "VALUES (?,?,?,?,?,?)",
                (filename, source, currency, len(values), _now_iso(), "billing"),
            )
            import_id = cur.lastrowid
            conn.executemany(
                """INSERT INTO billing
                (import_id, invoice_date, provider, service, project, region, environment,
                 resource_id, resource_type, usage_amount, unit, unit_price, amount, currency, sku)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(import_id, *row) for row in values],
            )
            report["currencies"][currency] = len(values)
            imported.append(currency)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if report["rejected"]:
        report["warnings"].append(
            f"{report['rejected']} row(s) were rejected and not written. "
            "Only the accepted rows are in the dataset."
        )
    if mode == "replace":
        report["warnings"].append(
            "The previous dataset (including demo findings and resources) was replaced."
        )
    return _finish(report, total, imported)


# --------------------------------------------------------------------------- #
# Resource inventory
# --------------------------------------------------------------------------- #
def import_resources(
    conn: sqlite3.Connection,
    filename: str,
    content: str,
    mode: str = "replace",
    source: str = "upload",
    default_currency: str = "USD",
) -> Dict[str, Any]:
    if mode not in ("replace", "append"):
        raise ImportRejected("mode must be 'replace' or 'append'.")

    currency_hint = (default_currency or "USD").strip().upper()
    if currency_hint not in ALLOWED_CURRENCIES:
        raise ImportRejected(
            f"Unsupported default currency '{default_currency}'. "
            f"Supported: {', '.join(ALLOWED_CURRENCIES)}."
        )

    header, rows = _split_rows(content)
    _require_headers(header, RESOURCE_REQUIRED, "resources")

    has_cost = "cost_per_hour" in header
    has_cpu = "cpu_pct" in header
    has_currency = "currency" in header

    report = _new_report("resources", filename, mode)
    if not has_cost:
        report["warnings"].append(
            "No cost_per_hour column found, so monthly baselines are recorded as 0. "
            "Add a cost column to get meaningful savings estimates."
        )
    if not has_cpu:
        report["warnings"].append(
            "No CPU column found, so every resource is treated as 0% utilized. "
            "Add cpu_pct (or cpu_avg_pct) to get accurate findings."
        )
    if not has_currency:
        report["warnings"].append(
            f"No currency column found; every row is recorded as {currency_hint}. "
            "No FX conversion is applied."
        )

    prepared: Dict[str, Dict[str, tuple]] = {}
    valid_rows = 0

    for line, record in rows:
        raw_currency = (record.get("currency") or "").strip().upper()
        currency = raw_currency or currency_hint
        if currency not in ALLOWED_CURRENCIES:
            _add_error(
                report, line,
                f"Unsupported currency '{record.get('currency', '')}'. "
                f"Supported: {', '.join(ALLOWED_CURRENCIES)}.",
            )
            continue

        resource_id = (record.get("resource_id") or "").strip()
        if not resource_id:
            _add_error(report, line, "resource_id is required.")
            continue
        name = (record.get("name") or "").strip() or resource_id

        cost_raw = record.get("cost_per_hour", "")
        cost = parse_decimal(cost_raw)
        if cost is None:
            if has_cost:
                _add_error(report, line, "cost_per_hour must be a number.")
                continue
            cost = Decimal("0")

        cpu = _parse_float(record.get("cpu_pct", ""), 0.0)
        memory = _parse_float(record.get("memory_pct", ""), 0.0)
        if not (0 <= cpu <= 1000 and 0 <= memory <= 1000):
            _add_error(report, line, "cpu_pct and memory_pct must be percentages.")
            continue

        status = (record.get("status") or "").strip()
        if not status:
            status = "idle" if cpu < 15 else ("under_utilized" if cpu < 45 else "ok")

        prepared.setdefault(currency, {})[resource_id] = (
            (
                resource_id,
                name,
                (record.get("resource_type") or "unknown").strip(),
                (record.get("provider") or "").strip() or "unknown",
                (record.get("environment") or RESOURCE_OPTIONAL_DEFAULTS["environment"]).strip(),
                (record.get("region") or RESOURCE_OPTIONAL_DEFAULTS["region"]).strip(),
                currency,
                money(cost),
                cpu,
                memory,
                status,
                (record.get("sku") or "").strip(),
            )
        )
        valid_rows += 1

    total = sum(len(v) for v in prepared.values())
    if total == 0:
        _finish(report, 0, [])
        return report

    if valid_rows > total:
        report["warnings"].append(
            f"{valid_rows - total} duplicate resource row(s) were collapsed to the latest "
            "snapshot per resource_id."
        )

    imported: List[str] = []
    try:
        if mode == "replace":
            for table in ("decisions", "findings", "resources"):
                conn.execute(f"DELETE FROM {table}")
        for currency, values in sorted(prepared.items()):
            unique_values = list(values.values())
            conn.executemany(
                """INSERT OR REPLACE INTO resources
                (resource_id, name, resource_type, provider, environment, region, currency,
                 cost_per_hour, cpu_pct, memory_pct, status, sku)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                unique_values,
            )
            cur = conn.execute(
                "INSERT INTO imports (filename, source, currency, row_count, imported_at, dataset) "
                "VALUES (?,?,?,?,?,?)",
                (filename, source, currency, len(unique_values), _now_iso(), "resources"),
            )
            del cur
            report["currencies"][currency] = len(unique_values)
            imported.append(currency)

        generated = generate_findings_for_imported_resources(
            conn,
            [c for c in imported],
            [rid for currency in imported for rid in prepared[currency]],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    report["findings_generated"] = generated
    if generated:
        report["warnings"].append(
            f"{generated} finding(s) were derived from this inventory using simple CPU thresholds. "
            "Review the evidence before acting."
        )
    if report["rejected"]:
        report["warnings"].append(
            f"{report['rejected']} row(s) were rejected and not written."
        )
    return _finish(report, total, imported)


def generate_findings_for_imported_resources(
    conn: sqlite3.Connection,
    currencies: Optional[List[str]] = None,
    resource_ids: Optional[List[str]] = None,
) -> int:
    """Create transparent, threshold-based findings for imported resources.

    Findings are only generated for resources sourced from uploads, and they state the
    threshold logic and the missing publishable SKU rather than inventing one.
    """
    uploaded = {
        row[0]
        for row in conn.execute("SELECT DISTINCT currency FROM imports WHERE dataset='resources'").fetchall()
    }
    if currencies:
        uploaded &= set(currencies)
    if not uploaded:
        return 0

    placeholders = ",".join("?" for _ in uploaded)
    query = f"SELECT * FROM resources WHERE currency IN ({placeholders})"
    params: List[Any] = sorted(uploaded)
    if resource_ids:
        ids = sorted(set(resource_ids))
        query += f" AND resource_id IN ({','.join('?' for _ in ids)})"
        params.extend(ids)
    query += " ORDER BY resource_id"
    rows = conn.execute(query, tuple(params)).fetchall()

    generated = 0
    for r in rows:
        cpu = float(r["cpu_pct"])
        if cpu >= 45:
            continue
        finding_type = "idle_resource" if cpu < 15 else "rightsize"
        baseline = money(Decimal(str(r["cost_per_hour"])) * Decimal("730"))
        evidence = [
            f"CPU utilization {cpu:.1f}% (imported inventory snapshot)",
            f"Memory utilization {float(r['memory_pct']):.1f}%",
            f"Reported status: {r['status'] or 'not provided'}",
        ]
        assumptions = [
            "Baseline monthly cost = cost_per_hour x 730 hours, in the same currency; no FX conversion.",
            "Thresholds applied by this build: idle < 15% CPU, rightsize < 45% CPU.",
        ]
        warnings = [
            "Derived from your imported snapshot, not from a live cloud API.",
            "Confirm with the resource owner before stopping or resizing.",
        ]
        if r["environment"] == "production":
            warnings.append("Resource is marked production; policy requires approval for changes.")
        conn.execute(
            """INSERT OR REPLACE INTO findings
            (id, resource_id, finding_type, currency, baseline_monthly_cost, current_sku,
             recommended_sku, evidence, assumptions, warnings, confidence, risk)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"f-auto-{r['resource_id']}",
                r["resource_id"],
                finding_type,
                r["currency"],
                baseline,
                r["sku"] or "not provided",
                "smaller SKU (see provider catalogue)",
                json.dumps(evidence),
                json.dumps(assumptions),
                json.dumps(warnings),
                "high" if cpu < 5 else "medium",
                "medium" if r["environment"] == "production" else "low",
            ),
        )
        generated += 1
    return generated


# --------------------------------------------------------------------------- #
# Dataset status and reset
# --------------------------------------------------------------------------- #
def data_status(conn: sqlite3.Connection) -> Dict[str, Any]:
    sources = [r[0] for r in conn.execute("SELECT DISTINCT source FROM imports").fetchall()]
    if not sources:
        mode = "empty"
    elif sources == ["sample"]:
        mode = "demo"
    elif "sample" in sources:
        mode = "mixed"
    else:
        mode = "imported"

    currencies: List[Dict[str, Any]] = []
    rows = conn.execute(
        """SELECT currency, COUNT(*) AS rows, MIN(invoice_date) AS start, MAX(invoice_date) AS end,
                  SUM(CAST(amount AS REAL)) AS total
           FROM billing GROUP BY currency ORDER BY currency"""
    ).fetchall()
    for row in rows:
        currency = row["currency"]
        resources = conn.execute(
            "SELECT COUNT(*) FROM resources WHERE currency=?", (currency,)
        ).fetchone()[0]
        findings = conn.execute(
            "SELECT COUNT(*) FROM findings WHERE currency=?", (currency,)
        ).fetchone()[0]
        curated = conn.execute(
            "SELECT COUNT(*) FROM imports WHERE currency=? AND source='sample'", (currency,)
        ).fetchone()[0]
        uploaded = conn.execute(
            "SELECT COUNT(*) FROM imports WHERE currency=? AND source!='sample'", (currency,)
        ).fetchone()[0]
        currencies.append(
            {
                "currency": currency,
                "rows": row["rows"],
                "start": row["start"],
                "end": row["end"],
                "total": money(row["total"] or 0),
                "resources": resources,
                "findings": findings,
                "origin": "mixed" if curated and uploaded else ("demo" if curated else "uploaded"),
            }
        )

    return {
        "mode": mode,
        "currencies": currencies,
        "total_rows": sum(c["rows"] for c in currencies),
        "allowed_currencies": ALLOWED_CURRENCIES,
        "last_import_at": (
            conn.execute("SELECT MAX(imported_at) FROM imports").fetchone()[0] or None
        ),
    }


def reset_data(conn: sqlite3.Connection, mode: str = "demo") -> Dict[str, Any]:
    if mode not in ("demo", "empty"):
        raise ImportRejected("mode must be 'demo' or 'empty'.")
    for table in ("decisions", "findings", "resources", "billing", "imports"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    if mode == "demo":
        seed_db(conn)
    return {"ok": True, "mode": mode, "status": data_status(conn)}


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
BILLING_TEMPLATE = """invoice_date,provider,service,project,region,environment,resource_id,resource_type,usage_amount,unit,unit_price,amount,currency,sku
2026-11-01,AWS,Amazon EC2,platform,us-east-1,production,i-0abc123,ec2,730,Hrs,0.1920,140.16,USD,m5.large
2026-11-02,Azure,Azure Virtual Machines,payments,westeurope,production,vm-eu-01,vm,730,Hrs,0.1700,124.10,EUR,Standard_B2s
2026-11-03,AWS,Amazon RDS,ledger,ap-south-1,production,db-in-01,rds,730,Hrs,12.33,9000.90,INR,db.t3.medium
"""

RESOURCE_TEMPLATE = """resource_id,name,resource_type,provider,environment,region,currency,cost_per_hour,cpu_pct,memory_pct,status,sku
i-0abc123,web-prod-01,ec2,AWS,production,us-east-1,USD,0.192,6,22,idle,m5.large
vm-eu-01,batch-eu,vm,Azure,production,westeurope,EUR,0.17,38,55,under_utilized,Standard_B2s
db-in-01,ledger-db,rds,AWS,production,ap-south-1,INR,12.33,55,60,ok,db.t3.medium
"""


def template(dataset: str) -> str:
    if dataset == "resources":
        return RESOURCE_TEMPLATE
    return BILLING_TEMPLATE
