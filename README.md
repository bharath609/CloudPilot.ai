# CloudPilot AI

**AI-assisted cloud cost and resource optimization — local-first, evidence-first, and safe by design.**

CloudPilot AI ingests cloud billing and utilization exports, validates them with
row-level precision, and stores exact-decimal records that later milestones turn
into spend analytics, waste findings, savings scenarios, forecasts and
human-approved optimization plans.

> **Status: Milestone 1 (backend + ingestion) is complete.** Cost analytics,
> findings, forecasting, the AI advisor and the dashboard are intentionally not
> built yet — see [Roadmap](#roadmap).
>
> **All sample data is synthetic.** The application holds no cloud credentials
> and cannot create, resize, stop or delete any cloud resource.

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
| 39 automated tests | ✅ Milestone 1 |
| Spend summaries, trends, breakdowns | ⏳ Milestone 2 |
| Findings, price catalogue, savings scenarios | ⏳ Milestone 3 |
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
```

Green nodes are implemented. Detailed design, decisions and trade-offs:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

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

# Seed the synthetic sample (run from the repository root in a second shell)
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

Configuration lives in `.env` (copy `.env.example`). No secrets are required.

## API (Milestone 1)

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health`, `/api/health` | Liveness/readiness, including database check |
| POST | `/api/imports/billing` | Upload a billing CSV (`?force=true` to bypass hash duplicate check) |
| POST | `/api/imports/utilization` | Upload a utilization CSV |
| GET | `/api/imports` | Paginated history, filter by `kind` and `status` |
| GET | `/api/imports/{id}` | Import status, counts, stats, issue totals |
| GET | `/api/imports/{id}/errors` | Paginated row-level issues, filter by `severity` |
| GET | `/api/imports/{id}/records` | Preview normalized records for audit |

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

Field-by-field rules, error codes and database columns:
[`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md). Data policy and currency
assumptions: [`data/README.md`](data/README.md).

CSV requirements: UTF-8 (BOM tolerated), comma-delimited, exact snake_case
headers, ISO dates/timestamps, decimal strings for money. Extra columns are
retained in raw row data but ignored by analysis.

## Correctness guarantees

1. **No binary floating point for money.** `Decimal` is stored as scaled
   `BIGINT` through a SQLAlchemy type decorator. SQL `SUM()` is integer addition,
   so totals are exact on SQLite and PostgreSQL. A test asserts that
   `0.1 + 0.2 + 0.0000005` round-trips as `0.300001`, both through SQLAlchemy and
   through raw SQL.
2. **Currencies are never silently mixed.** A multi-currency file is stored but
   flagged `mixed_currency`; every record carries its ISO code and no FX
   conversion exists yet.
3. **Bad rows never corrupt good data.** Structural errors reject the whole file.
   Row errors persist only the valid rows and report each rejected row with a
   row number, column, code and message. `CLOUDPILOT_STRICT_IMPORTS=true` switches
   to all-or-nothing.
4. **Replays are visible.** SHA-256 rejects byte-identical uploads with `409`;
   forced replays and overlapping business keys are flagged, not hidden.
5. **No cloud access.** There is no provider SDK and no write path.

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

Actual result on this machine (Python 3.14.7, 16 Nov 2026):

```text
39 passed, 1 warning in 11.28s
All checks passed!
```

The single warning is an upstream Starlette notice that `httpx` should be
replaced by `httpx2`; it is not from this project. Coverage includes exact
totals against a hand-read CSV fixture, malformed encodings, NUL bytes, oversized
uploads, duplicate headers, missing columns, row limits, duplicate detection,
account masking, strict mode, pagination and transaction integrity.

## 5-minute demo

1. Start the API and open <http://127.0.0.1:8000/docs>.
2. Upload `data/sample/billing_sample.csv`; note `status=valid`, 480 rows,
   a single currency (`USD`) and the data window.
3. Upload `data/sample/utilization_sample.csv`; the 4 resources are recognised
   because billing was loaded first.
4. Upload `data/sample/billing_row_errors.csv`; show `status=partial` and open
   `/api/imports/{id}/errors` to inspect the precise row/column errors.
5. Upload `data/sample/billing_missing_column.csv`; show `status=invalid` and
   that `/records` is empty.
6. Upload the billing file again; show the `409 duplicate_import` with the
   original import ID. Retry with `?force=true` to see overlap warnings.
7. Fetch `/api/imports/{id}/records` and note that amounts are strings such as
   `"4.482123"` — exact decimals, not floats.
8. Run the tests and show the green output above.

Findings, savings, forecasts and AI explanations are not part of Milestone 1 and
are not simulated in the demo.

## Repository layout

```text
CloudPilot AI/
├── backend/
│   ├── app/
│   │   ├── main.py                 # app factory, lifespan, error envelope
│   │   ├── api/{deps.py,routes/}   # health + import endpoints
│   │   ├── core/                   # settings, enums, errors, UTC helpers
│   │   ├── db/                     # engine, exact decimal types, ORM models
│   │   ├── schemas/                # Pydantic response contracts
│   │   └── services/
│   │       ├── ingestion/          # CSV parser, validators, typed drafts
│   │       └── imports/            # transaction orchestration + lookups
│   ├── alembic/                    # migration 0001 initial schema
│   ├── tests/                      # 39 pytest tests
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
│   ├── sources.md                  # provenance rules (catalogue empty until M3)
│   └── catalogue/
├── scripts/
│   ├── generate_sample_data.py     # deterministic synthetic data
│   └── seed_sample_data.py         # load sample into the configured DB
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Roadmap

| Milestone | Scope | Exit check |
|---|---|---|
| **M2** | Decimal spend summaries, trends, breakdowns by service/project/region/environment | Totals and groupings match hand-calculated fixtures |
| **M3** | Idle/over-provisioned detection rules, sourced price catalogue, savings scenarios | Every finding links to evidence; every saving is reproducible |
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

## Known limitations (Milestone 1)

- No cost analytics endpoints yet; raw normalized records are inspectable but
  totals per service/project are Milestone 2.
- No authentication, rate limiting or TLS.
- No UI yet; use `/docs` or `curl`.
- Imports are append-only; there is no rollback/delete endpoint.
- Re-uploading an overlapping billing export warns but still stores the rows;
  a dedupe policy is an open question before analytics ships.
- `usage_unit` is shape-checked, not validated against a per-service allowlist.
- Utilization metrics reference billing resources by string ID; there is no
  resource inventory table yet.
- SQLite is fine for one local user; PostgreSQL is recommended for concurrency.
- The Docker Compose file passes `docker compose config`, but the image build
  was **not executed** on this machine because the Docker daemon was not
  running. Run `docker compose up --build` and report any build error before
  treating the container path as verified.

## Documentation

- [Architecture and decisions](docs/ARCHITECTURE.md)
- [Implementation plan and open questions](docs/IMPLEMENTATION_PLAN.md)
- [Data dictionary and error codes](docs/DATA_DICTIONARY.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Data policy and synthetic-data notice](data/README.md)
- [Pricing provenance rules](pricing/sources.md)
