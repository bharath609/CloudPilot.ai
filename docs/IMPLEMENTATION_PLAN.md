# CloudPilot AI — Implementation Plan

> Status key: `DONE` · `IN PROGRESS` · `PLANNED` · `BLOCKED`
>
> This plan follows the milestone order in `CloudPilot_AI_Full_Guide.md` §14.
> Only Milestone 1 is implemented so far. Later milestones are deliberately not
> started until the previous one is reviewed and approved.

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

### Milestone 1 — Backend and ingestion — `DONE` (awaiting review)

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
Result: 39 tests pass; lint clean. Live HTTP smoke test imported 480 billing
rows, 2,880 utilization rows, and a malformed file with 8 precise row errors.
The Docker image build was not run because the local Docker daemon was stopped;
`docker compose config` validates.

**Known limitations carried into Milestone 2**

- Cross-import duplicate rows are reported as warnings, not skipped, so
  re-uploaded corrected exports can be loaded. Analytics must therefore scope by
  import until a dedupe policy is approved.
- No authentication or multi-tenancy yet (local-first MVP, threat model §6).
- `usage_unit` is validated for shape, not against a per-service unit allowlist.
- Import rollback/void is not exposed. Imports are append-only for auditability.
- Forecast and price ingestion are not implemented (Milestones 3–4).

### Milestone 2 — Cost analytics — `PLANNED`

- Decimal aggregations by service, project, region, environment, provider.
- Currency-partitioned responses; reject mixed-currency totals.
- Trends (daily/monthly) and top cost drivers.
- Hand-calculated fixtures; SQL and Python totals must match.
- Scope default: single import or explicit date range.

**Exit check:** totals and groupings match known test cases.

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

### Milestone 5 — AI advisor — `PLANNED` (requires approval: may use external API)

- Provider adapter (local Ollama by default; OpenRouter only with user consent).
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

## 3. Milestone 1 API surface (implemented)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/api/health` | Liveness + DB check |
| POST | `/api/imports/billing` | Upload generic billing CSV |
| POST | `/api/imports/utilization` | Upload generic utilization CSV |
| GET | `/api/imports` | Paginated import history, filter by `kind`/`status` |
| GET | `/api/imports/{id}` | Import detail + summary counts |
| GET | `/api/imports/{id}/errors` | Paginated row-level issues |
| GET | `/api/imports/{id}/records` | Preview normalized rows (audit/debug) |

The remaining endpoints from guide §11 (`/api/costs/*`, `/api/analysis/*`, …)
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

## 5. Open questions for the user

1. **Database default:** SQLite for local dev + PostgreSQL in Compose is the
   current split. Keep it, or require PostgreSQL everywhere?
2. **Partial imports:** current behaviour keeps valid rows and reports bad ones.
   Should the default instead be all-or-nothing (`CLOUDPILOT_STRICT_IMPORTS=true`)?
3. **Duplicate policy across imports:** warning (current) vs skip vs reject.
4. **LLM provider for Milestone 5:** local Ollama (free/offline) preferred over a
   paid API? No provider will be added without approval.
5. **Report export format priority:** Markdown + CSV first, or PDF required?

Defaults are in place, so none of these block Milestone 1.
