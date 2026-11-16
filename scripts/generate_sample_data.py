"""Generate deterministic synthetic sample data for CloudPilot AI.

The data is entirely fabricated. It exists so the project can be demonstrated
and tested without cloud credentials. Do not treat any value as a real price.

Run from the repository root:

    python scripts/generate_sample_data.py
"""

from __future__ import annotations

import csv
import random
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = REPO_ROOT / "data" / "sample"

SEED = 20260101
START_DATE = date(2026, 1, 1)
DAYS = 60
MAX_AMOUNT = Decimal("0.000001")

BILLING_HEADER = [
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

UTILIZATION_HEADER = [
    "timestamp",
    "resource_id",
    "cpu_avg_pct",
    "cpu_p95_pct",
    "memory_avg_pct",
    "memory_p95_pct",
    "network_in_bytes",
    "network_out_bytes",
    "storage_used_pct",
    "sample_window_minutes",
]


def money(value: Decimal) -> Decimal:
    return value.quantize(MAX_AMOUNT, rounding=ROUND_HALF_UP)


# resource_id, provider, account_id, service, region, environment, project,
# quantity/day, usage_unit, monthly-ish unit price, team, owner
RESOURCES = [
    (
        "i-demo-0a1b2c3d4e5f",
        "aws",
        "demo-aws-account-001",
        "Amazon EC2",
        "eu-west-1",
        "prod",
        "checkout-platform",
        Decimal("24"),
        "Hrs",
        Decimal("0.1920"),
        "platform",
        "platform@example.test",
    ),
    (
        "i-demo-0a1b2c3d4e60",
        "aws",
        "demo-aws-account-001",
        "Amazon EC2",
        "eu-west-1",
        "staging",
        "checkout-platform",
        Decimal("24"),
        "Hrs",
        Decimal("0.1920"),
        "platform",
        "platform@example.test",
    ),
    (
        "i-demo-0a1b2c3d4e61",
        "aws",
        "demo-aws-account-001",
        "Amazon EC2",
        "eu-west-1",
        "dev",
        "sandbox",
        Decimal("24"),
        "Hrs",
        Decimal("0.0960"),
        "developer-experience",
        "devx@example.test",
    ),
    (
        "db-demo-postgres-01",
        "aws",
        "demo-aws-account-001",
        "Amazon RDS",
        "eu-west-1",
        "prod",
        "checkout-platform",
        Decimal("24"),
        "Hrs",
        Decimal("0.3500"),
        "platform",
        "platform@example.test",
    ),
    (
        "vol-demo-0a1b2c3d4e62",
        "aws",
        "demo-aws-account-001",
        "Amazon EBS",
        "eu-west-1",
        "prod",
        "checkout-platform",
        Decimal("100"),
        "GB-Mo",
        Decimal("0.0800") / Decimal(30),
        "platform",
        "platform@example.test",
    ),
    (
        "bucket-demo-logs-001",
        "aws",
        "demo-aws-account-001",
        "Amazon S3",
        "eu-west-1",
        "prod",
        "observability",
        Decimal("250"),
        "GB-Mo",
        Decimal("0.0230") / Decimal(30),
        "observability",
        "sre@example.test",
    ),
    (
        "vm-demo-azure-001",
        "azure",
        "demo-azure-subscription-001",
        "Virtual Machines",
        "westeurope",
        "prod",
        "data-platform",
        Decimal("24"),
        "Hrs",
        Decimal("0.1660"),
        "data-platform",
        "data@example.test",
    ),
    (
        "instance-demo-gcp-001",
        "gcp",
        "demo-gcp-project-001",
        "Compute Engine",
        "europe-west1",
        "dev",
        "ml-sandbox",
        Decimal("24"),
        "Hrs",
        Decimal("0.0475"),
        "ml",
        "ml@example.test",
    ),
]


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    print(f"wrote {path.relative_to(REPO_ROOT)} ({len(rows)} data rows)")


def generate_billing() -> None:
    rng = random.Random(SEED)
    rows: list[list[str]] = []
    for day_offset in range(DAYS):
        usage_date = START_DATE + timedelta(days=day_offset)
        for (
            resource_id,
            provider,
            account_id,
            service,
            region,
            environment,
            project,
            quantity,
            unit,
            price,
            team,
            owner,
        ) in RESOURCES:
            jitter = Decimal(str(round(rng.uniform(-0.03, 0.03), 6)))
            amount = money(price * quantity * (Decimal(1) + jitter))
            rows.append(
                [
                    usage_date.isoformat(),
                    provider,
                    account_id,
                    service,
                    resource_id,
                    region,
                    environment,
                    project,
                    str(quantity),
                    unit,
                    str(amount),
                    "USD",
                    team,
                    owner,
                ]
            )
    write_csv(SAMPLE_DIR / "billing_sample.csv", BILLING_HEADER, rows)


def generate_utilization() -> None:
    rng = random.Random(SEED + 1)
    rows: list[list[str]] = []
    profiles = [
        ("i-demo-0a1b2c3d4e5f", 42.0, 8.0, 61.0, 9.0),
        ("i-demo-0a1b2c3d4e60", 2.5, 1.5, 17.0, 4.0),
        ("i-demo-0a1b2c3d4e61", 1.2, 0.8, 9.0, 2.0),
        ("vm-demo-azure-001", 51.0, 10.0, 68.0, 8.0),
    ]
    end = datetime(2026, 3, 1, 23, 0, tzinfo=UTC)
    start = end - timedelta(days=30) + timedelta(hours=1)
    for resource_id, cpu_base, cpu_spread, mem_base, mem_spread in profiles:
        moment = start
        while moment <= end:
            cpu_avg = max(0.1, cpu_base + rng.uniform(-cpu_spread, cpu_spread))
            cpu_p95 = min(100.0, cpu_avg + rng.uniform(1.0, 6.0))
            memory_avg = max(1.0, mem_base + rng.uniform(-mem_spread, mem_spread))
            memory_p95 = min(100.0, memory_avg + rng.uniform(1.0, 5.0))
            storage_used = max(1.0, min(99.0, 45.0 + rng.uniform(-10.0, 10.0)))
            rows.append(
                [
                    moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    resource_id,
                    f"{cpu_avg:.3f}",
                    f"{cpu_p95:.3f}",
                    f"{memory_avg:.3f}",
                    f"{memory_p95:.3f}",
                    str(rng.randint(50_000, 5_000_000)),
                    str(rng.randint(20_000, 2_000_000)),
                    f"{storage_used:.3f}",
                    "60",
                ]
            )
            moment += timedelta(hours=1)
    rows.sort(key=lambda row: (row[0], row[1]))
    write_csv(SAMPLE_DIR / "utilization_sample.csv", UTILIZATION_HEADER, rows)


def generate_invalid_billing_rows() -> None:
    rows = [
        [
            "2026-02-01", "aws", "demo-aws-account-001", "Amazon EC2", "i-demo-dup-001",
            "eu-west-1", "dev", "sandbox", "24", "Hrs", "10.000000", "USD",
            "platform", "platform@example.test",
        ],
        [  # duplicate of the first row
            "2026-02-01", "aws", "demo-aws-account-001", "Amazon EC2", "i-demo-dup-001",
            "eu-west-1", "dev", "sandbox", "24", "Hrs", "10.000000", "USD",
            "platform", "platform@example.test",
        ],
        [  # impossible date
            "2026-02-30", "aws", "demo-aws-account-001", "Amazon EC2", "i-demo-dup-002",
            "eu-west-1", "dev", "sandbox", "24", "Hrs", "10.000000", "USD",
            "platform", "platform@example.test",
        ],
        [  # negative cost
            "2026-02-02", "aws", "demo-aws-account-001", "Amazon EC2", "i-demo-dup-003",
            "eu-west-1", "dev", "sandbox", "24", "Hrs", "-5.000000", "USD",
            "platform", "platform@example.test",
        ],
        [  # unsupported currency
            "2026-02-03", "aws", "demo-aws-account-001", "Amazon EC2", "i-demo-dup-004",
            "eu-west-1", "dev", "sandbox", "24", "Hrs", "10.000000", "XYZ",
            "platform", "platform@example.test",
        ],
        [  # unsupported provider
            "2026-02-04", "oracle", "demo-oracle-001", "Compute", "i-demo-dup-005",
            "eu-frankfurt-1", "dev", "sandbox", "24", "Hrs", "10.000000", "USD",
            "platform", "platform@example.test",
        ],
        [  # unsupported environment
            "2026-02-05", "aws", "demo-aws-account-001", "Amazon EC2", "i-demo-dup-006",
            "eu-west-1", "production", "sandbox", "24", "Hrs", "10.000000", "USD",
            "platform", "platform@example.test",
        ],
        [  # missing required service
            "2026-02-06", "aws", "demo-aws-account-001", "", "i-demo-dup-007",
            "eu-west-1", "dev", "sandbox", "24", "Hrs", "10.000000", "USD",
            "platform", "platform@example.test",
        ],
        [  # NaN is not a finite decimal
            "2026-02-07", "aws", "demo-aws-account-001", "Amazon EC2", "i-demo-dup-008",
            "eu-west-1", "dev", "sandbox", "24", "Hrs", "NaN", "USD",
            "platform", "platform@example.test",
        ],
        [  # second genuinely valid row
            "2026-02-08", "aws", "demo-aws-account-001", "Amazon S3", "i-demo-dup-009",
            "eu-west-1", "dev", "sandbox", "1", "GB-Mo", "12.500000", "USD",
            "platform", "platform@example.test",
        ],
    ]
    write_csv(SAMPLE_DIR / "billing_row_errors.csv", BILLING_HEADER, rows)


def generate_missing_column() -> None:
    header = [column for column in BILLING_HEADER if column != "cost_amount"]
    rows = [
        [
            "2026-02-01", "aws", "demo-aws-account-001", "Amazon EC2", "i-demo-missing-001",
            "eu-west-1", "dev", "sandbox", "24", "Hrs", "USD",
            "platform", "platform@example.test",
        ]
    ]
    write_csv(SAMPLE_DIR / "billing_missing_column.csv", header, rows)


def generate_multicurrency() -> None:
    rows = [
        [
            "2026-02-10", "aws", "demo-aws-account-001", "Amazon EC2", "i-demo-fx-001",
            "eu-west-1", "dev", "sandbox", "24", "Hrs", "4.608000", "USD",
            "platform", "platform@example.test",
        ],
        [
            "2026-02-10", "azure", "demo-azure-subscription-001", "Virtual Machines",
            "vm-demo-fx-002", "westeurope", "dev", "sandbox", "24", "Hrs",
            "3.984000", "EUR", "platform", "platform@example.test",
        ],
    ]
    write_csv(SAMPLE_DIR / "billing_multicurrency.csv", BILLING_HEADER, rows)


def generate_invalid_utilization_rows() -> None:
    rows = [
        [
            "2026-03-02T00:00:00Z", "i-demo-0a1b2c3d4e5f", "10.000", "15.000",
            "20.000", "25.000", "1000", "500", "40.000", "60",
        ],
        [  # duplicate resource/timestamp
            "2026-03-02T00:00:00Z", "i-demo-0a1b2c3d4e5f", "10.000", "15.000",
            "20.000", "25.000", "1000", "500", "40.000", "60",
        ],
        [  # invalid hour
            "2026-03-02T25:00:00Z", "i-demo-0a1b2c3d4e5f", "10.000", "15.000",
            "20.000", "25.000", "1000", "500", "40.000", "60",
        ],
        [  # CPU above 100
            "2026-03-02T02:00:00Z", "i-demo-0a1b2c3d4e5f", "120.000", "125.000",
            "20.000", "25.000", "1000", "500", "40.000", "60",
        ],
        [  # negative memory
            "2026-03-02T03:00:00Z", "i-demo-0a1b2c3d4e5f", "10.000", "15.000",
            "-5.000", "25.000", "1000", "500", "40.000", "60",
        ],
        [  # non-integer network bytes
            "2026-03-02T04:00:00Z", "i-demo-0a1b2c3d4e5f", "10.000", "15.000",
            "20.000", "25.000", "1.5", "500", "40.000", "60",
        ],
        [  # observation window out of range
            "2026-03-02T05:00:00Z", "i-demo-0a1b2c3d4e5f", "10.000", "15.000",
            "20.000", "25.000", "1000", "500", "40.000", "0",
        ],
        [  # valid but internally inconsistent p95 (warning, still accepted)
            "2026-03-02T06:00:00Z", "i-demo-0a1b2c3d4e5f", "10.000", "5.000",
            "20.000", "25.000", "1000", "500", "40.000", "60",
        ],
    ]
    write_csv(SAMPLE_DIR / "utilization_row_errors.csv", UTILIZATION_HEADER, rows)


def main() -> None:
    generate_billing()
    generate_utilization()
    generate_invalid_billing_rows()
    generate_missing_column()
    generate_multicurrency()
    generate_invalid_utilization_rows()
    print("Synthetic sample data generated. All values are fabricated.")


if __name__ == "__main__":
    main()
