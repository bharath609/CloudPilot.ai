"""SQLite database layer with a deterministic synthetic seed.

Money is stored as exact decimal strings (TEXT) alongside its currency.
No FX conversion is ever applied: each row keeps its original currency.
"""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional

from .config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    source TEXT NOT NULL,
    currency TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    imported_at TEXT NOT NULL,
    dataset TEXT NOT NULL DEFAULT 'billing'
);

CREATE TABLE IF NOT EXISTS billing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL,
    invoice_date TEXT NOT NULL,
    provider TEXT NOT NULL,
    service TEXT NOT NULL,
    project TEXT NOT NULL,
    region TEXT NOT NULL,
    environment TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    usage_amount REAL NOT NULL,
    unit TEXT NOT NULL,
    unit_price TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    sku TEXT NOT NULL,
    FOREIGN KEY (import_id) REFERENCES imports(id)
);

CREATE TABLE IF NOT EXISTS resources (
    resource_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    environment TEXT NOT NULL,
    region TEXT NOT NULL,
    currency TEXT NOT NULL,
    cost_per_hour TEXT NOT NULL,
    cpu_pct REAL NOT NULL,
    memory_pct REAL NOT NULL,
    status TEXT NOT NULL,
    sku TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    finding_type TEXT NOT NULL,
    currency TEXT NOT NULL,
    baseline_monthly_cost TEXT NOT NULL,
    current_sku TEXT NOT NULL,
    recommended_sku TEXT NOT NULL,
    evidence TEXT NOT NULL,
    assumptions TEXT NOT NULL,
    warnings TEXT NOT NULL,
    confidence TEXT NOT NULL,
    risk TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    note TEXT,
    reviewer TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def money(value: Any) -> str:
    """Quantize a numeric value to a 2dp exact decimal string."""
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    """FastAPI dependency yielding a short-lived connection."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def dicts(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Seed data definition
# --------------------------------------------------------------------------- #
# (provider, service, resource_type, region, environment, sku, unit, base_daily)
SERVICES: Dict[str, List[tuple]] = {
    "USD": [
        ("AWS", "Amazon EC2", "ec2", "us-east-1", "production", "m5.xlarge", "Hrs", 230.0),
        ("AWS", "Amazon S3", "s3", "us-east-1", "production", "standard", "GB-Mo", 45.0),
        ("Azure", "Azure Virtual Machines", "vm", "eastus", "production", "Standard_D4s_v3", "Hrs", 120.0),
        ("GCP", "Google Compute Engine", "gce", "us-central1", "staging", "n2-standard-4", "Hrs", 80.0),
        ("Azure", "Azure SQL Database", "sql", "eastus", "production", "S2", "Hrs", 60.0),
    ],
    "EUR": [
        ("AWS", "Amazon EC2", "ec2", "eu-west-1", "production", "m5.large", "Hrs", 120.0),
        ("Azure", "Azure Virtual Machines", "vm", "westeurope", "production", "Standard_D2s_v3", "Hrs", 90.0),
        ("GCP", "Google Compute Engine", "gce", "europe-west1", "production", "n2-standard-2", "Hrs", 55.0),
    ],
    "INR": [
        ("AWS", "Amazon EC2", "ec2", "ap-south-1", "production", "m5.large", "Hrs", 9000.0),
        ("Azure", "Azure Virtual Machines", "vm", "centralindia", "production", "Standard_B2s", "Hrs", 5000.0),
        ("AWS", "Amazon RDS", "rds", "ap-south-1", "production", "db.t3.medium", "Hrs", 3500.0),
    ],
}

RESOURCES = [
    # resource_id, name, type, provider, env, region, currency, cost_per_hour, cpu, mem, status, sku
    ("r-ec2-001", "web-prod-01", "ec2", "AWS", "production", "us-east-1", "USD", "0.42", 6.0, 22.0, "idle", "m5.xlarge"),
    ("r-ec2-002", "api-prod-02", "ec2", "AWS", "production", "us-east-1", "USD", "0.68", 71.0, 63.0, "ok", "m5.2xlarge"),
    ("r-rds-001", "orders-db", "rds", "AWS", "production", "us-east-1", "USD", "0.95", 40.0, 55.0, "under_utilized", "db.r5.xlarge"),
    ("r-s3-001", "media-bucket", "s3", "AWS", "production", "us-east-1", "USD", "0.02", 0.0, 0.0, "ok", "standard"),
    ("r-ec2-eu-01", "web-eu-01", "ec2", "AWS", "production", "eu-west-1", "EUR", "0.38", 8.0, 19.0, "idle", "m5.large"),
    ("r-vm-eu-01", "batch-eu", "vm", "Azure", "production", "westeurope", "EUR", "0.51", 64.0, 70.0, "ok", "Standard_D4s_v3"),
    ("r-ec2-in-01", "web-in-01", "ec2", "AWS", "production", "ap-south-1", "INR", "12.50", 9.0, 25.0, "idle", "m5.large"),
    ("r-rds-in-01", "ledger-db", "rds", "AWS", "production", "ap-south-1", "INR", "22.00", 55.0, 60.0, "under_utilized", "db.t3.large"),
]

FINDINGS = [
    (
        "f-usd-1", "r-ec2-001", "idle_resource", "USD", "302.40", "m5.xlarge", "m5.large",
        ["p95 CPU 6% over 30 days", "no network egress spikes", "attached to production environment"],
        ["Baseline is de-duplicated imported billing; no FX conversion is applied.",
         "Low utilization is not proof of waste; an owner must confirm the workload can be stopped."],
        ["Downtime risk if the workload is stateful.", "Verify maintenance windows before acting."],
        "high", "low",
    ),
    (
        "f-usd-2", "r-ec2-002", "rightsize", "USD", "489.60", "m5.2xlarge", "m5.xlarge",
        ["CPU p95 71% (bursty)", "memory p95 63%", "no sustained saturation"],
        ["Proposed cost scales baseline by catalogue price ratio; same provider/region/currency.",
         "No FX conversion or negotiated discount is applied."],
        ["Validate peak-hour headroom before resizing."],
        "medium", "medium",
    ),
    (
        "f-usd-3", "r-rds-001", "idle_resource", "USD", "684.00", "db.r5.xlarge", "db.r5.large",
        ["Connections below 15% of provisioned", "CPU p95 40%", "storage growth flat"],
        ["Downsizing assumes connection and storage headroom remain sufficient."],
        ["Database resizes may require a maintenance window."],
        "medium", "medium",
    ),
    (
        "f-eur-1", "r-ec2-eu-01", "idle_resource", "EUR", "273.60", "m5.large", "t3.medium",
        ["p95 CPU 8% over 30 days", "no egress spikes"],
        ["Baseline is de-duplicated imported billing in EUR; no FX conversion is applied."],
        ["Confirm the instance is not part of a HA failover pair."],
        "high", "low",
    ),
    (
        "f-eur-2", "r-vm-eu-01", "rightsize", "EUR", "367.20", "Standard_D4s_v3", "Standard_D2s_v3",
        ["CPU p95 64%", "memory p95 70%"],
        ["Price ratio from catalogue in EUR; no FX conversion is applied."],
        ["Validate batch latency targets before downsizing."],
        "medium", "medium",
    ),
    (
        "f-inr-1", "r-ec2-in-01", "idle_resource", "INR", "9000.00", "m5.large", "t3.small",
        ["p95 CPU 9% over 30 days", "no egress spikes"],
        ["Baseline is de-duplicated imported billing in INR; no FX conversion is applied."],
        ["Confirm no scheduled batch jobs depend on this host."],
        "high", "low",
    ),
    (
        "f-inr-2", "r-rds-in-01", "rightsize", "INR", "15840.00", "db.t3.large", "db.t3.medium",
        ["CPU p95 55%", "storage growth moderate"],
        ["Price ratio from catalogue in INR; no FX conversion is applied."],
        ["Database resizes may require a maintenance window."],
        "medium", "medium",
    ),
]


def seed_db(conn: sqlite3.Connection, days: int = 60) -> None:
    """Populate a deterministic synthetic dataset across USD/EUR/INR."""
    rng = random.Random(20261125)
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)

    for currency, services in SERVICES.items():
        row_count = days * len(services)
        cur = conn.execute(
            "INSERT INTO imports (filename, source, currency, row_count, imported_at) VALUES (?,?,?,?,?)",
            (f"billing-{currency.lower()}.csv", "sample", currency, row_count, _now_iso()),
        )
        import_id = cur.lastrowid

        for day_offset in range(days):
            day = start + timedelta(days=day_offset)
            for idx, (provider, service, rtype, region, env, sku, unit, base) in enumerate(services):
                wobble = 1.0 + rng.uniform(-0.08, 0.10)
                amount = Decimal(str(base * wobble))
                usage = 24.0
                unit_price = amount / Decimal(str(usage))
                conn.execute(
                    """INSERT INTO billing
                    (import_id, invoice_date, provider, service, project, region, environment,
                     resource_id, resource_type, usage_amount, unit, unit_price, amount, currency, sku)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        import_id, day.isoformat(), provider, service, "platform", region, env,
                        f"{rtype}-{currency.lower()}-{idx + 1}", rtype, usage, unit,
                        money(unit_price), money(amount), currency, sku,
                    ),
                )

    conn.executemany(
        """INSERT OR REPLACE INTO resources
        (resource_id, name, resource_type, provider, environment, region, currency,
         cost_per_hour, cpu_pct, memory_pct, status, sku)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        RESOURCES,
    )

    for f in FINDINGS:
        (fid, rid, ftype, currency, baseline, cur_sku, rec_sku,
         evidence, assumptions, warnings, confidence, risk) = f
        conn.execute(
            """INSERT OR REPLACE INTO findings
            (id, resource_id, finding_type, currency, baseline_monthly_cost, current_sku,
             recommended_sku, evidence, assumptions, warnings, confidence, risk)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                fid, rid, ftype, currency, baseline, cur_sku, rec_sku,
                json.dumps(evidence), json.dumps(assumptions), json.dumps(warnings),
                confidence, risk,
            ),
        )

    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first schema without losing data."""
    import_columns = {row["name"] for row in conn.execute("PRAGMA table_info(imports)")}
    if "dataset" not in import_columns:
        conn.execute("ALTER TABLE imports ADD COLUMN dataset TEXT NOT NULL DEFAULT 'billing'")

    resource_columns = {row["name"] for row in conn.execute("PRAGMA table_info(resources)")}
    if "sku" not in resource_columns:
        conn.execute("ALTER TABLE resources ADD COLUMN sku TEXT NOT NULL DEFAULT ''")
    conn.commit()


def init_db(seed: bool = True) -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
        if seed:
            count = conn.execute("SELECT COUNT(*) FROM billing").fetchone()[0]
            if count == 0:
                seed_db(conn)
    finally:
        conn.close()


def reset_db(seed: bool = True) -> None:
    """Drop all data and recreate (used by scripts/tests)."""
    conn = connect()
    try:
        for table in ("decisions", "findings", "resources", "billing", "imports"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    finally:
        conn.close()
    init_db(seed=seed)
