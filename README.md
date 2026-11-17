# CloudPilot AI

**AI-assisted cloud cost and resource optimization — local-first, evidence-first, and safe by design.**

CloudPilot AI ingests cloud billing and utilization exports, validates them with
row-level precision, stores exact-decimal records, and turns them into spend
analytics, evidence-backed waste findings and reproducible savings scenarios.
Forecasting, the AI advisor and the approval workflow arrive in later milestones.

> **Status: Milestones 1–3 (ingestion, cost analytics and waste detection) are
> complete.** Forecasting, the AI advisor and the dashboard are intentionally not
> built yet — see [Roadmap](#roadmap).
>
> **All sample data and demo prices are synthetic.** The application holds no
> cloud credentials and cannot create, resize, stop or delete any cloud resource.

---

## The problem

Cloud bills are difficult to interpret and waste is easy to miss. Recruiters and
hiring managers can reproduce every result in this repository in about five
minutes: upload the synthetic billing and utilization files, inspect validation
quality, and see how money is stored exactly rather than through floating point.

The end goal is a FinOps assistant that explains cost drivers, forecasts spend,
and produces **evidence-backed, human-reviewed** savings recommendations. An LLM
will only ever explain numbers that deterministic code already computed.

## What works today

| Capability | Status |
|---|---|
| Generic billing CSV ingestion with row-level validation | ✅ Milestone 1 |
| Generic utilization CSV ingestion with row-level validation | ✅ Milestone 1 |
| Exact `Decimal` money storage (scaled `BIGINT`, no floats) | ✅ Milestone 1 |
| Structural + field + relationship validation, duplicate detection | ✅ Milestone 1 |
| Append-only import audit trail (SHA-256, row counts, raw rows) | ✅ Milestone 1 |
| Paginated import/issue/record inspection API | ✅ Milestone 1 |
| Alembic migrations, SQLite and PostgreSQL, Docker Compose | ✅ Milestone 1 |
| Spend summary, breakdown and trends with exact Decimal aggregation | ✅ Milestone 2 |
| Currency-partitioned totals, business-key de-duplication | ✅ Milestone 2 |
| Idle-resource detection with observation-window minimums | ✅ Milestone 3 |
| Rightsizing using sourced catalogue prices and explicit SKUs | ✅ Milestone 3 |
| Evidence-linked findings, assumptions, warnings, confidence and risk | ✅ Milestone 3 |
| Reproducible savings scenarios with synthetic-price disclosure | ✅ Milestone 3 |
| 58 automated tests | ✅ Milestones 1–3 |
| Forecasts with evaluation | ⏳ Milestone 4 |
| Evidence-grounded AI advisor | ⏳ Milestone 5 |
| React dashboard, exports, approvals | ⏳ Milestones 6–7 |

## Architecture

```mermaid
flowchart TD
  A[Billing CSV] --> B[Ingestion and structural validation]
  C[Utilization CSV] --> B
  B --> D[Field validation and normalization]
  D --> E[(Imports · cost records · metrics · issues)]
  E --> F[Cost analytics - M2]
  E --> G[Waste detection - M3]
  P[Price catalogue with source and date - M3] --> H[Savings scenarios - M3]
  G --> H
  F --> I[Forecasting - M4]
  H --> J[Evidence package]
  I --> J
  J --> K[AI explanation only - M5]
  K --> L[Human review and approval - M6]
  L --> M[Report export - M6]

  style B fill:#e8f5e9,stroke:#2e7d32
  style D fill:#e8f5e9,stroke:#2e7d32
  style E fill:#e8f5e9,stroke:#2e7d32
  style F fill:#e8f5e9,stroke:#2e7d32
  style G fill:#e8f5e9,stroke:#2e7d32
  style H fill:#e8f5e9,stroke:#2e7d32
  style P fill:#e8f5e9,stroke:#2e7d32
```

Green nodes are implemented through Milestone 3. Detailed design, decisions and
trade-offs: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quick start

### Option A — Docker Compose (PostgreSQL)

```bash
docker compose up --build
```

- API: <http://127.0.0.1:8000>
- Interactive docs: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/api/health>

Containers bind to `127.0.0.1` only. Migrations run automatically at startup.
Upload the host-side sample files with the `curl` commands below.

### Option B — Local Python (SQLite, no Docker)

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"

# Database schema (creates/updates the SQLite file at the repository root)
cd backend
..\.venv\Scripts\alembic.exe upgrade head

# Seed the synthetic sample and demo price catalogue
# (run from the repository root in a second shell)
cd ..
.\.venv\Scripts\python.exe scripts\seed_sample_data.py

# Start the API
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e "./backend[dev]"

cd backend
alembic upgrade head
cd ..
python scripts/seed_sample_data.py
cd backend
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs>.

If you prefer not to seed the database, upload the CSV files instead:

```powershell
# Windows
curl.exe -s -F "file=@data/sample/billing_sample.csv;type=text/csv" http://127.0.0.1:8000/api/imports/billing
curl.exe -s -F "file=@data/sample/utilization_sample.csv;type=text/csv" http://127.0.0.1:8000/api/imports/utilization
```

```bash
# Linux / macOS
curl -s -F "file=@data/sample/billing_sample.csv;type=text/csv" http://127.0.0.1:8000/api/imports/billing
curl -s -F "file=@data/sample/utilization_sample.csv;type=text/csv" http://127.0.0.1:8000/api/imports/utilization
```

If you upload instead of seeding, load the demo catalogue separately:

```bash
python scripts/load_price_catalogue.py
```

Then run waste detection and inspect the findings:

```powershell
# Windows
curl.exe -s -X POST http://127.0.0.1:8000/api/analysis/run -H "Content-Type: application/json" -d "{}"
curl.exe -s http://127.0.0.1:8000/api/findings
```

```bash
# Linux / macOS
curl -s -X POST http://127.0.0.1:8000/api/analysis/run -H "Content-Type: application/json" -d '{}'
curl -s http://127.0.0.1:8000/api/findings
```

Configuration lives in `.env` (copy `.env.example`). No secrets are required.

## API (Milestones 1–3)

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health`, `/api/health` | Liveness/readiness, including database check |
| POST | `/api/imports/billing` | Upload a billing CSV (`?force=true` to bypass hash duplicate check) |
| POST | `/api/imports/utilization` | Upload a utilization CSV |
| GET | `/api/imports` | Paginated history, filter by `kind` and `status` |
| GET | `/api/imports/{id}` | Import status, counts, stats, issue totals |
| GET | `/api/imports/{id}/errors` | Paginated row-level issues, filter by `severity` |
| GET | `/api/imports/{id}/records` | Preview normalized records for audit |
| GET | `/api/costs/summary` | Spend totals by currency, row counts, data window |
| GET | `/api/costs/breakdown` | Spend by `service`, `project`, `region`, `environment`, `provider`, `account` or `resource` |
| GET | `/api/costs/trends` | Daily (`day`) or monthly (`month`) series |
| GET | `/api/prices` | Sourced catalogue prices, filterable by provider/SKU/region/currency/date |
| GET | `/api/prices/{id}` | One price entry with full provenance |
| POST | `/api/analysis/run` | Run deterministic waste detection (optional scope body) |
| GET | `/api/findings` | Findings from the latest run, or `?run_id=` a specific run |
| GET | `/api/findings/{id}` | Finding detail, evidence and stored scenario |

All three cost endpoints accept `start`, `end`, `currency`, `provider`,
`account_id`, `service`, `region`, `environment` and `project`. `breakdown` adds
`dimension` and `limit` (rows per currency, largest first — this is also the
top-cost-driver view). `trends` adds `granularity`. Dates are inclusive.

`POST /api/analysis/run` accepts an optional JSON body with the same scope fields
(except dates). The cost window is the latest 30 days of matching billing data
(configurable), and utilization must fall inside that window. `GET /api/findings`
defaults to the newest run; pass `run_id`, `finding_type`, `status`, `currency`,
`limit` or `offset` to filter.

Example analytics response (abridged):

```json
{
  "window": { "start": "2026-01-01", "end": "2026-03-01", "days": 60 },
  "totals": [{ "currency": "USD", "amount": "1531.305850", "row_count": 480 }],
  "row_count": 480,
  "excluded_duplicate_rows": 0,
  "import_ids": [1],
  "import_count": 1,
  "contains_sample_data": true,
  "notes": [
    "Amounts are exact decimals from imported billing rows; no FX conversion is applied.",
    "Rows are de-duplicated by business key; the earliest stored record wins."
  ]
}
```

Amounts are JSON strings, never floats. Each currency is reported separately;
there is no FX conversion and no combined multi-currency total.

Example finding (abridged, synthetic sample data):

```json
{
  "finding_type": "over_provisioned",
  "resource_id": "i-demo-0a1b2c3d4e5f",
  "currency": "USD",
  "current_sku": "demo.ec2.c5.2xlarge",
  "recommended_sku": "demo.ec2.c5.xlarge",
  "baseline_monthly_cost": "138.396963",
  "proposed_monthly_cost": "69.198482",
  "estimated_monthly_savings": "69.198481",
  "savings_pct": "50.000",
  "confidence": "high",
  "risk": "medium",
  "cost_window_start": "2026-01-31",
  "cost_window_end": "2026-03-01",
  "observation_days": 30,
  "sample_count": 720,
  "uses_synthetic_prices": true,
  "evidence": {
    "cost_record_ids": [242, 250, "..."],
    "metric_ids": [1, 5, "..."],
    "cost_record_id_count": 30,
    "metric_id_count": 720
  },
  "assumptions": [
    "Proposed cost scales the baseline by the catalogue price ratio ..."
  ],
  "warnings": [
    "Owner review is required before changing the resource size.",
    "The price catalogue is synthetic demo data, not a vendor price list or quote."
  ],
  "scenario": {
    "method": "rightsize_sku",
    "baseline_monthly_cost": "138.396963",
    "proposed_monthly_cost": "69.198482",
    "estimated_monthly_savings": "69.198481"
  }
}
```

The full run is reproducible from the sample CSVs with `Decimal` arithmetic;
`docs/IMPLEMENTATION_PLAN.md` records the independent calculation. The demo
catalogue uses `example.invalid` URLs and is never presented as a vendor quote.

Example upload response (abridged):

```json
{
  "id": 1,
  "kind": "billing",
  "filename": "billing_sample.csv",
  "status": "valid",
  "row_count": 480,
  "accepted_row_count": 480,
  "rejected_row_count": 0,
  "warning_count": 0,
  "currencies": ["USD"],
  "period_start": "2026-01-01",
  "period_end": "2026-03-01",
  "issues": [],
  "issues_truncated": false,
  "message": "Imported 480 rows."
}
```

Errors use one envelope everywhere:

```json
{
  "error": {
    "code": "duplicate_import",
    "message": "This exact file was already imported. Use force=true to import it again.",
    "details": { "import_id": 1, "kind": "billing", "status": "valid" }
  }
}
```

## Data contracts

| Input | Contract | Synthetic samples |
|---|---|---|
| Billing | [`data/schemas/billing.schema.json`](data/schemas/billing.schema.json) | `billing_sample.csv`, `billing_row_errors.csv`, `billing_missing_column.csv`, `billing_multicurrency.csv` |
| Utilization | [`data/schemas/utilization.schema.json`](data/schemas/utilization.schema.json) | `utilization_sample.csv`, `utilization_row_errors.csv` |
| Price catalogue | [`pricing/sources.md`](pricing/sources.md) | `pricing/catalogue/demo_prices.csv` (all `is_synthetic=true`) |

Field-by-field rules, error codes and database columns:
[`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md). Data policy and currency
assumptions: [`data/README.md`](data/README.md).

CSV requirements: UTF-8 (BOM tolerated), comma-delimited, exact snake_case
headers, ISO dates/timestamps, decimal strings for money. The billing `sku`
column is optional and accepted without a warning. Other extra columns are
retained in raw row data but ignored by analysis.

## Correctness guarantees

1. **No binary floating point for money.** `Decimal` is stored as scaled
   `BIGINT` through a SQLAlchemy type decorator. SQL `SUM()` is integer addition,
   so totals are exact on SQLite and PostgreSQL. A test asserts that
   `0.1 + 0.2 + 0.0000005` round-trips as `0.300001`, both through SQLAlchemy and
   through raw SQL.
2. **Currencies are never silently mixed.** Totals are grouped by ISO currency,
   and every record carries its code. A multi-currency file is stored but flagged
   `mixed_currency`. No FX conversion exists, so a USD total and a EUR total are
   never added together.
3. **Bad rows never corrupt good data.** Structural errors reject the whole file.
   Row errors persist only the valid rows and report each rejected row with a
   row number, column, code and message. `CLOUDPILOT_STRICT_IMPORTS=true` switches
   to all-or-nothing.
4. **Replays never double-count.** SHA-256 rejects byte-identical uploads with
   `409`; forced replays are stored for audit but analytics keep only the
   earliest row per business key and report `excluded_duplicate_rows`.
5. **No cloud access.** There is no provider SDK and no write path.
6. **No invented savings.** Every finding links to de-duplicated billing rows,
   utilization sample IDs and, for rightsizing, exact catalogue price entries.
   Missing SKUs or prices produce no finding and are disclosed. Low utilization is
   a review signal, not proof of waste. Synthetic prices are flagged on the
   finding and the run.

| Situation | Persisted | Status |
|---|---|---|
| All rows valid, no warnings | all rows | `valid` |
| Warnings only | all rows | `valid_with_warnings` |
| Some rows rejected | valid rows only | `partial` |
| Every row rejected / structural failure / strict mode | import audit row only | `invalid` |
| Byte-identical file already imported | nothing new | HTTP `409` |

## Tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
..\.venv\Scripts\ruff.exe check .
```

Actual result on this machine (Python 3.14.7, 17 Nov 2026):

```text
58 passed, 1 warning in 34.07s
All checks passed!
```

The single warning is an upstream Starlette notice that `httpx` should be
replaced by `httpx2`; it is not from this project. Coverage includes exact
totals against a hand-read CSV fixture, malformed encodings, NUL bytes, oversized
uploads, duplicate headers, missing columns, row limits, duplicate detection,
account masking, strict mode, pagination, transaction integrity,
hand-calculated analytics totals with per-currency shares and de-duplication,
catalogue idempotence and provenance, optional SKU ingestion, idle and
rightsizing rules, observation minimums, missing-price behaviour, currency
partitioning of savings, evidence links, and reproducibility across runs.

### Container path verified

On the same machine, `docker compose build` completed and
`docker compose up -d --wait` reported both `db` and `api` as healthy. Uploading
the samples against `http://127.0.0.1:8000` (PostgreSQL 16) returned the same
results as the SQLite run: billing `valid` 480/480, utilization `valid` 2,880/2,880,
malformed billing `partial` 2 accepted / 8 rejected, amounts serialized as
strings, and `alembic_version = 0001`. The analytics endpoints also matched
SQLite exactly (USD `1531.305850`, the same top-five services and the same three
monthly buckets); a forced re-import reported 480 duplicate warnings and
`excluded_duplicate_rows=480` without changing any total. In PostgreSQL,
`cost_records.amount` is stored as `bigint`, so `SUM(amount)` is exact integer
addition. `docker compose config --quiet` also passes.

The Milestone 3 path was verified on the same PostgreSQL 16 stack. After the
image rebuild, `alembic upgrade head` advanced the database to `0002`, and the
seed script loaded 480 billing rows, 2,880 utilization rows and 4 synthetic
prices. `POST /api/analysis/run` returned the same three findings as SQLite with
total savings USD `276.720019` for `2026-01-31..2026-03-01`:
`i-demo-0a1b2c3d4e5f` `138.396963 → 69.198482` (saving `69.198481`),
`i-demo-0a1b2c3d4e60` `138.563898` and `i-demo-0a1b2c3d4e61` `68.957640`
(idle, proposed `0`). `GET /api/findings/1` showed 30 cost-record IDs and 720
metric IDs (capped at 50), 4 assumptions, 4 warnings and the two synthetic
catalogue price entries. A second run produced run 2 with identical savings while
run 1 stayed queryable by `run_id`. Row counts after teardown confirmed 2 runs,
6 findings and 6 scenarios. The stack and its PostgreSQL volume were then
removed with `docker compose down -v`.

## 5-minute demo

1. Start the API and open <http://127.0.0.1:8000/docs>.
2. Upload `data/sample/billing_sample.csv`; note `status=valid`, 480 rows,
   a single currency (`USD`), the data window and the optional `sku` values.
3. Upload `data/sample/utilization_sample.csv`; the 4 resources are recognised
   because billing was loaded first.
4. Run `python scripts/load_price_catalogue.py`, then
   `GET /api/prices`; note 4 entries, all `is_synthetic=true`, with
   `example.invalid` source URLs.
5. `POST /api/analysis/run` with `{}`. The sample returns 2 idle findings and
   1 rightsizing finding, total USD `276.720019` for `2026-01-31..2026-03-01`.
6. Open `/api/findings`: each finding shows baseline, proposed, savings, evidence
   IDs, observation days, assumptions, warnings, confidence and risk. The
   rightsizing finding shows the two catalogue price entries; the idle findings
   assume a full-window stop.
7. Run the analysis again and compare: a new immutable run has identical
   arithmetic, while `GET /api/findings?run_id=1` still returns the first run.
8. Upload `data/sample/billing_row_errors.csv`; show `status=partial` and open
   `/api/imports/{id}/errors` to inspect the precise row/column errors.
9. Upload `data/sample/billing_missing_column.csv`; show `status=invalid` and
   that `/records` is empty.
10. Upload the billing file again; show the `409 duplicate_import` with the
    original import ID. Retry with `?force=true` to see overlap warnings.
11. Open `/api/costs/summary`: USD `1531.305850` over 480 rows for
    `2026-01-01..2026-03-01`. The same total comes from a plain `Decimal` read of
    the CSV, not from the database path.
12. Open `/api/costs/breakdown?dimension=service&limit=5` and
    `/api/costs/trends?granularity=month`; shares are percentages of one currency
    and the three monthly buckets add back to the same total.
13. Run the tests and show the green output above.

All findings and prices in this demo are synthetic. Forecasts and AI explanations
are not part of Milestones 1–3 and are not simulated.

## Repository layout

```text
CloudPilot AI/
├── backend/
│   ├── app/
│   │   ├── main.py                 # app factory, lifespan, error envelope
│   │   ├── api/{deps.py,routes/}   # health, import and cost endpoints
│   │   ├── core/                   # settings, enums, errors, UTC helpers
│   │   ├── db/                     # engine, exact decimal types, ORM models
│   │   ├── schemas/                # Pydantic response contracts
│   │   └── services/
│   │       ├── ingestion/          # CSV parser, validators, typed drafts
│   │       ├── imports/            # transaction orchestration + lookups
│   │       ├── analytics.py        # Decimal aggregations + de-duplication
│   │       ├── analysis.py         # idle/rightsize rules + evidence/scenarios
│   │       └── prices.py           # catalogue loader, provenance, exact lookup
│   ├── alembic/                    # migrations 0001 initial, 0002 waste detection
│   ├── tests/                      # 58 pytest tests
│   └── pyproject.toml
├── data/
│   ├── sample/                     # synthetic valid + malformed CSVs
│   ├── schemas/                    # CSV JSON contracts
│   └── README.md
├── docs/
│   ├── IMPLEMENTATION_PLAN.md
│   ├── ARCHITECTURE.md
│   ├── DATA_DICTIONARY.md
│   └── THREAT_MODEL.md
├── pricing/
│   ├── sources.md                  # provenance rules
│   └── catalogue/demo_prices.csv   # clearly labelled synthetic catalogue
├── scripts/
│   ├── generate_sample_data.py     # deterministic synthetic data
│   ├── seed_sample_data.py         # load sample + catalogue into the configured DB
│   └── load_price_catalogue.py     # idempotent catalogue refresh
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Roadmap

| Milestone | Scope | Exit check |
|---|---|---|
| ✅ **M1** | Ingestion, validation, exact-decimal storage, import audit | Totals exact; malformed rows reported precisely |
| ✅ **M2** | Decimal spend summaries, trends, breakdowns with currency partitioning and business-key de-duplication | Totals and groupings match hand-calculated fixtures |
| ✅ **M3** | Idle/over-provisioned detection rules, sourced price catalogue, savings scenarios | Every finding links to evidence; every saving is reproducible |
| **M4** | Transparent forecasting with train/test split and error metrics | Forecast reproducible and evaluated |
| **M5** | Evidence-bounded AI advisor (local model preferred), typed output, injection tests | AI explains without inventing prices or changing totals |
| **M6** | React dashboard, filters, sample-data badge, approvals, exports | Full workflow in the browser |
| **M7** | CI, release hardening, screenshots, `v1.0.0` | `docker compose up --build` demo passes from scratch |

Details and open questions: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).

## Security posture

- No cloud credentials, provider SDKs or write operations exist.
- Upload size, row count, encoding and numeric ranges are bounded.
- SQL is parameterized through SQLAlchemy; filenames are reduced to a basename.
- 12-digit account IDs are masked before storage.
- CSV content is inert text; it is never executed. AI prompt-injection defenses
  arrive with the advisor in Milestone 5.
- The API has **no authentication** and binds locally. Do not expose it to a
  network until M7 hardening lands.

Full STRIDE-style analysis: [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Known limitations (Milestones 1–3)

- Analytics are read-only and computed on demand; there is no materialized cache.
  Fine at local sample sizes, but large exports will need pre-aggregation.
- De-duplication matches the exact business key
  (`usage_date, provider, account_id, service, resource_id, usage_unit, amount`).
  A restated export with a *changed* amount is a new key and is counted in
  addition to the original; supersede/version semantics are not implemented.
- Breakdowns apply `limit` per currency, so a multi-currency response can contain
  more than `limit` items in total.
- Shares are rounded to three decimal places per row; they may not sum to exactly
  `100.000` when many small groups exist.
- No authentication, rate limiting or TLS.
- No UI yet; use `/docs` or `curl`.
- Imports are append-only; there is no rollback/delete endpoint.
- `usage_unit` is shape-checked, not validated against a per-service allowlist.
- Utilization metrics reference billing resources by string ID; there is no
  resource inventory table yet.
- Waste detection uses fixed, explainable thresholds, not statistical anomaly
  detection. Low utilization is a review signal, not proof of waste.
- The shipped price catalogue is **synthetic**. Real savings require a sourced
  catalogue; the loader validates structure and provenance fields, not vendor
  accuracy. There is no live price API and no FX conversion.
- Rightsizing assumes the smaller SKU is suitable and uses list prices; it does
  not model performance, network, storage or negotiated discounts.
- Idle scenarios assume a full-window stop with no replacement spend.
- Only resources present in billing **and** with utilization in the window are
  evaluated. Missing SKUs/prices produce no finding and are disclosed.
- Findings are immutable audit records; there is no edit, acknowledge or approval
  endpoint yet (Milestone 6).
- SQLite is fine for one local user; PostgreSQL is recommended for concurrency.
- The container image runs on Python 3.12 while local development used 3.14.7;
  both pass the same HTTP checks, but the test suite is executed on the host.
- No CI pipeline yet; tests and lint are run manually.

## Documentation

- [Architecture and decisions](docs/ARCHITECTURE.md)
- [Implementation plan and open questions](docs/IMPLEMENTATION_PLAN.md)
- [Data dictionary and error codes](docs/DATA_DICTIONARY.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Data policy and synthetic-data notice](data/README.md)
- [Pricing provenance rules](pricing/sources.md)
