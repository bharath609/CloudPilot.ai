# CloudPilot AI — Implementation Plan

> Status key: `DONE` · `IN PROGRESS` · `PLANNED` · `BLOCKED`
>
> This plan follows the milestone order in `CloudPilot_AI_Full_Guide.md` §14.
> Milestones 1–2 are implemented. Later milestones are deliberately not started
> until the previous one is reviewed and approved.

## 1. Guiding constraints

1. Deterministic Python computes every cost and saving. The LLM (Milestone 5)
   only explains figures that already exist in a structured evidence package.
2. Money is always `decimal.Decimal`, stored exactly (see ADR-002).
3. Currencies are never summed together without an explicit FX source and date.
4. The application never writes to a cloud provider. Read-only CSVs only.
5. Synthetic sample data is clearly labelled; no paid APIs or cloud accounts are
   used to build or demo this.
6. Tests must be run and their real output reported. No invented results.

## 2. Milestones

### Milestone 0 — Planning and sample data — `DONE`

| Task | Status |
|---|---|
| Repository scaffold (`backend/`, `data/`, `docs/`, `pricing/`, `scripts/`) | DONE |
| Generic billing and utilization CSV contracts | DONE — `data/schemas/*.schema.json` |
| Synthetic sample dataset + deliberately malformed fixtures | DONE — `data/sample/` |
| Planning docs (implementation, architecture, data dictionary, threat model) | DONE |
| Currency and pricing assumptions documented | DONE — `data/README.md`, `pricing/sources.md` |

**Exit check:** sample files pass schema validation and include deliberately
malformed rows for tests.
Result: conforming files import cleanly; malformed fixtures produce row-level
errors. Verified in `backend/tests/`.

### Milestone 1 — Backend and ingestion — `DONE`

| Task | Status |
|---|---|
| FastAPI app factory, typed settings, error envelope | DONE |
| SQLAlchemy models for imports, cost records, utilization metrics, validation errors | DONE |
| Alembic initial migration | DONE |
| `POST /api/imports/billing` | DONE |
| `POST /api/imports/utilization` | DONE |
| `GET /api/imports/{id}` + list + row errors | DONE |
| Structural validation: encoding, size, row limit, header, duplicate/missing columns | DONE |
| Field validation: dates, decimals, ranges, enums, currencies, IDs | DONE |
| Duplicate detection (within file = error, across imports = warning) | DONE |
| Row-level error persistence + import audit metadata (SHA-256, row counts) | DONE |
| Decimal-safe persistence and exact round-trip tests | DONE |
| Seed script for sample data | DONE |
| Docker Compose (PostgreSQL + API) | DONE |

**Exit check:** valid CSV imports; invalid CSV reports precise errors without
corrupting data.
Result: 39 tests passed at the M1 exit (49 now, including M2 analytics); lint clean. Live HTTP smoke test imported 480 billing
rows, 2,880 utilization rows, and a malformed file with 8 precise row errors.
`docker compose build` succeeded and both containers reported healthy;
`docker compose up -d --wait` plus HTTP uploads against PostgreSQL returned the
same counts as SQLite, with `amount` stored as `bigint` and `alembic_version=0001`.
Milestone 2 analytics on PostgreSQL matched SQLite exactly
(USD `1531.305850`, identical top-five services and monthly buckets), and a
forced re-import reported `excluded_duplicate_rows=480` with unchanged totals.

**Known limitations carried into Milestone 2**

- Cross-import duplicate rows are stored with a warning; analytics exclude them
  by business key (resolved in Milestone 2).
- No authentication or multi-tenancy yet (local-first MVP, threat model §6).
- `usage_unit` is validated for shape, not against a per-service unit allowlist.
- Import rollback/void is not exposed. Imports are append-only for auditability.
- Forecast and price ingestion are not implemented (Milestones 3–4).

### Milestone 2 — Cost analytics — `DONE` (awaiting review)

Approved decisions before starting:

| Decision | Choice |
|---|---|
| Database default | Keep SQLite for local dev; PostgreSQL via Compose |
| Import policy | Partial by default; strict via `CLOUDPILOT_STRICT_IMPORTS` |
| Cross-import duplicates | Store for audit, exclude from analytics (earliest business key wins) |
| LLM provider (M5) | Local Ollama, optional and disabled by default |
| Export priority (M6) | Markdown + CSV first, PDF later |

| Task | Status |
|---|---|
| `GET /api/costs/summary` — totals by currency, row counts, window, import provenance | DONE |
| `GET /api/costs/breakdown` — service/project/region/environment/provider/account/resource | DONE |
| `GET /api/costs/trends` — daily and monthly, currency-partitioned | DONE |
| Filters: inclusive date window, currency, provider, account, service, region, environment, project | DONE |
| Currency partitioning; mixed-currency responses never summed | DONE |
| Business-key de-duplication + `excluded_duplicate_rows` disclosure | DONE |
| `Decimal` aggregation over scaled `BIGINT` (`SUM` is integer addition) | DONE |
| Hand-calculated fixture tests; per-currency share rounding | DONE |

**Exit check:** totals and groupings match known test cases.
Result: 49 tests pass; lint clean. All amounts are exact `Decimal` strings.
Independent verification: a plain `Decimal` read of
`data/sample/billing_sample.csv` produced USD `1531.305850`; the live API
(`/api/costs/summary`), the service breakdown (top five services) and the monthly
trend (Jan `791.676052`, Feb `714.440385`, Mar `25.189413`) matched it exactly.
Forced re-import of a 5-row fixture stored 5 rows but `excluded_duplicate_rows=5`
kept totals unchanged.

**Known limitations carried into Milestone 3**

- De-duplication uses the exact business key. A restated export with a changed
  amount is a new key and is counted in addition to the original; supersede
  semantics are not implemented.
- Breakdown `limit` is per currency, so multi-currency responses can exceed it.
- Shares are rounded to 3 dp per row and may not sum to exactly `100.000`.
- Aggregations run on every request; no cache or pre-aggregation yet.
- No authentication or multi-tenancy yet (local-first MVP, threat model §6).
- `usage_unit` is validated for shape, not against a per-service unit allowlist.
- Import rollback/void is not exposed. Imports are append-only for auditability.

### Milestone 3 — Resource analysis and savings scenarios — `PLANNED`

- Utilization import is done; detection rules next.
- Configurable idle rules with a minimum observation window.
- Price catalogue with source URL, retrieval date, effective period.
- Savings scenarios with baseline/proposed cost and explicit assumptions.
- Every finding links to cost + metric evidence IDs.

**Exit check:** every finding links to evidence and every savings number is
reproducible.

### Milestone 4 — Forecasting — `PLANNED`

- Transparent baseline first (seasonal naive / moving average).
- Train/test split, MAE/MAPE, prediction intervals where defensible.
- Explicit small-sample warnings.

**Exit check:** forecast reproducible and evaluated on held-out periods.

### Milestone 5 — AI advisor — `PLANNED`

- Provider adapter: local Ollama by default, optional and disabled; no paid API.
- Bounded evidence package, typed JSON output, evidence-ID validation.
- Reject numeric price/savings claims absent from the package.
- Timeout, retry, redaction, deterministic fallback explanation.
- Prompt-injection tests using hostile CSV text.

**Exit check:** AI explains findings without changing totals or inventing savings.

### Milestone 6 — Frontend — `PLANNED`

- React + TypeScript + Vite, Recharts.
- Overview, Cost Explorer, Resource Health, Findings, AI Advisor, Forecasts,
  Imports, Audit.
- Sample-data badge, freshness indicators, approval history, exports.

**Exit check:** recruiter can import sample files and explore the whole workflow.

### Milestone 7 — Quality and release — `PLANNED`

- Full unit/integration/API test matrix, GitHub Actions (ruff, mypy, pytest).
- Docker image hardening, screenshots, architecture diagram, demo dataset.
- README 5-minute demo, tag `v1.0.0`.

## 3. API surface (implemented)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/api/health` | Liveness + DB check |
| POST | `/api/imports/billing` | Upload generic billing CSV |
| POST | `/api/imports/utilization` | Upload generic utilization CSV |
| GET | `/api/imports` | Paginated import history, filter by `kind`/`status` |
| GET | `/api/imports/{id}` | Import detail + summary counts |
| GET | `/api/imports/{id}/errors` | Paginated row-level issues |
| GET | `/api/imports/{id}/records` | Preview normalized rows (audit/debug) |
| GET | `/api/costs/summary` | Spend totals by currency + data window |
| GET | `/api/costs/breakdown` | Spend by dimension, largest first |
| GET | `/api/costs/trends` | Daily/monthly series by currency |

The remaining endpoints from guide §11 (`/api/analysis/*`, `/api/findings/*`, …)
arrive in their own milestones.

## 4. Key risks

| Risk | Mitigation | Milestone |
|---|---|---|
| Float contamination of money | Exact scaled-BIGINT `Decimal` type; tests | M1 |
| Silent currency mixing | Per-currency grouping; import flags mixed currency | M1/M2 |
| Malformed CSV corrupting data | Structural gate + row validation + transaction | M1 |
| CSV formula / prompt injection | Cells stored as inert text; never executed; AI prompt hardening | M1/M5 |
| Overclaiming savings | Evidence + assumptions + confidence required on every scenario | M3 |
| Scope creep | One milestone per review, explicit exit checks | all |
| Synthetic data mistaken for live | `data_source` field, UI badge, README banner | M1/M6 |

## 5. Decisions (resolved before Milestone 2)

1. **Database default:** SQLite for local dev; PostgreSQL via Docker Compose.
2. **Partial imports:** partial is the default; strict is opt-in via
   `CLOUDPILOT_STRICT_IMPORTS=true`.
3. **Cross-import duplicates:** store for audit, exclude from analytics by exact
   business key (earliest stored row wins). `excluded_duplicate_rows` discloses it.
4. **LLM provider:** local Ollama only, optional and disabled by default; no paid
   API.
5. **Export priority:** Markdown + CSV first in Milestone 6, PDF later.

No open questions block Milestone 3. New decisions will be recorded here.
