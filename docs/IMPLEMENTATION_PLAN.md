# CloudPilot AI — Implementation Plan

> Status key: `DONE` · `IN PROGRESS` · `PLANNED` · `BLOCKED`
>
> This plan follows the milestone order in `CloudPilot_AI_Full_Guide.md` §14.
> Milestones 1–4 are implemented. Later milestones are deliberately not started
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

### Milestone 2 — Cost analytics — `DONE`

Approved decisions before starting:

| Decision | Choice |
|---|---|
| Database default | Keep SQLite for local dev; PostgreSQL via Compose |
| Import policy | Partial by default; strict via `CLOUDPILOT_STRICT_IMPORTS` |
| Cross-import duplicates | Store for audit, exclude from analytics (earliest business key wins) |
| LLM provider (M5) | Provider-agnostic OpenAI-compatible free-tier API (Groq documented default; Gemini/OpenRouter/Ollama interchangeable), optional and disabled by default; no paid API |
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

### Milestone 3 — Resource analysis and savings scenarios — `DONE`

Decisions taken before implementation:

| Decision | Choice |
|---|---|
| Idle rule | Maximum CPU p95 `< 15%` **and** maximum memory p95 `< 30%` |
| Rightsize rule | Mean CPU `< 50%` **and** mean memory `< 70%` (evaluated only when not idle) |
| Observation minimum | 14 distinct days and 24 samples; default cost window 30 days |
| Minimum saving | `1.00` in the billing currency |
| Price catalogue | `pricing/catalogue/demo_prices.csv`, every row sourced and flagged `is_synthetic=true` |
| SKU linkage | Optional billing `sku` column; no SKU is inferred from resource names |
| Rightsizing math | Catalogue list-price ratio for the same provider, region, currency and usage unit; no FX |
| Currency policy | Findings are partitioned by currency; totals are never combined |

| Task | Status |
|---|---|
| Optional `sku` column accepted with no `unexpected_column` warning | DONE |
| `PriceEntry`, `AnalysisRun`, `Finding`, `SavingsScenario` tables + migration `0002` | DONE |
| Idempotent catalogue loader with provenance and validation | DONE |
| `GET /api/prices`, `GET /api/prices/{id}` | DONE |
| `POST /api/analysis/run` | DONE |
| `GET /api/findings` (latest run by default, or `run_id`) and `GET /api/findings/{id}` | DONE |
| Evidence IDs, observation window, assumptions, warnings, confidence and risk | DONE |
| Reproducible scenarios stored per finding | DONE |
| Tests for rules, observation minimum, missing prices, idempotence, currency partitioning, reproducibility | DONE |

**Exit check:** every finding links to evidence and every savings number is
reproducible.
Result: 58 tests pass; lint clean. On the SQLite sample, the API returns three
findings (2 idle, 1 over-provisioned) with total savings USD `276.720019` for
`2026-01-31..2026-03-01`. An independent `Decimal` read of
`data/sample/billing_sample.csv` reproduced each baseline
(`138.396963`, `138.563898`, `68.957640`), the rightsize proposal
(`69.198482` = baseline × `0.096000 / 0.192000`) and the same total. Running the
analysis twice creates a second immutable run with identical savings; the first
run remains queryable by `run_id`. Migration `0002` passed
`upgrade head -> downgrade base -> upgrade head`.

The same flow was verified against PostgreSQL 16 in Docker Compose. The rebuilt
image ran `alembic upgrade head` to `0002`; the seed script loaded 480 billing
rows, 2,880 utilization rows and 4 synthetic prices. `POST /api/analysis/run`
returned the identical three findings and USD `276.720019` total, with the same
baselines (`138.396963`, `138.563898`, `68.957640`) and rightsize proposal
(`69.198482`). The finding detail exposed 30 cost-record IDs, 720 metric IDs
(truncated at 50), four assumptions, four warnings and both synthetic price
entries. A second run reproduced the arithmetic as run 2 while run 1 remained
queryable. Table counts confirmed 2 runs, 6 findings and 6 scenarios, then the
stack and volume were removed with `docker compose down -v`.

**Known limitations carried into Milestone 4**

- Rules are deliberately simple threshold rules, not statistical anomaly
  detection. Low utilization is a review signal, not proof of waste.
- The shipped price catalogue is synthetic demo data. Real prices require a
  sourced catalogue with real URLs and retrieval dates; the loader validates
  shape, not vendor accuracy.
- Rightsizing assumes the smaller SKU is suitable; performance, network and
  storage requirements are not modelled.
- Idle scenarios assume a full-window stop with zero replacement spend.
- Only resources that appear in billing **and** have utilization in the window
  are evaluated. There is no resource inventory or live discovery.
- Catalogue prices are list prices; negotiated discounts and commitments are not
  applied.
- No approval workflow or export yet (Milestone 6).

### Milestone 4 — Forecasting — `DONE`

Decisions taken before implementation:

| Decision | Choice |
|---|---|
| Granularity | Daily, per ISO currency; no combined multi-currency total |
| Default method | `seasonal_naive` with a 7-day season; `moving_average` as the alternative |
| Default horizon | 30 days (request range 1–90) |
| Evaluation | Chronological 14-day holdout (request range 1–60), predicted strictly from earlier data |
| Minimum history | 28 days, inclusive of the holdout; maximum 365 days retained |
| Missing days | Calendar days without billing rows count as zero spend |
| Prediction interval | Empirical 90% quantile of absolute holdout residuals, applied symmetrically and clamped at zero |
| Metrics | MAE, RMSE, signed bias, MAPE excluding zero-actual days, interval width, `mape_excluded_points` |
| Confidence | `high` ≥90 days and MAPE ≤15%; `medium` ≥42 days and MAPE ≤30%; otherwise `low` |
| Warnings | Short history (<56 days), short holdout (<14 days), unavailable MAPE, degenerate interval, horizon > holdout, flat moving-average forecast |
| Persistence | Immutable `forecast_runs` + `forecast_points`; migration `0003` |

| Task | Status |
|---|---|
| `ForecastMethod` / `ForecastGranularity` enums and forecast settings | DONE |
| `ForecastRun` / `ForecastPoint` tables + migration `0003` | DONE |
| De-duplicated daily spend per currency, zero-filled calendar days | DONE |
| Seasonal-naive and moving-average baselines | DONE |
| Held-out evaluation with MAE/RMSE/bias/MAPE and explicit exclusions | DONE |
| Empirical prediction intervals and confidence/warning rules | DONE |
| `POST /api/forecasts/run`, `GET /api/forecasts`, `GET /api/forecasts/{run_id}` | DONE |
| Tests with hand-derived metrics, zero-holdout, insufficient history, filters, currencies, reproducibility | DONE |

**Exit check:** forecast reproducible and evaluated on held-out periods.

Result: 66 tests pass; lint clean. Migration `0003` passed
`upgrade head -> downgrade base -> upgrade head` on SQLite. On the synthetic
sample, `POST /api/forecasts/run` with the default 30-day seasonal-naive request
returned one USD series over history `2026-01-01..2026-03-01` and horizon
`2026-03-02..2026-03-31`:

| Value | Result |
|---|---|
| Projected total | USD `765.016323` |
| Projected interval | `752.864703..777.167943` |
| MAE | `0.183786` |
| RMSE | `0.232832` |
| Bias | `-0.026085` |
| MAPE | `0.720%` (0 excluded points) |
| Interval width | `0.405054` |
| Confidence | `medium` |

The model was trained on the first 46 days and scored on the final 14, which it
never saw. A separate script re-read `data/sample/billing_sample.csv` with plain
`csv` and `Decimal`, rebuilt the seasonal-naive holdout and future forecasts, and
matched all 30 stored daily points and every metric exactly; mismatches were
`none`. A `moving_average` run produced a flat 7-day projection of USD
`178.504515` with width `0.317761`, and both runs remained queryable.

The same request was verified on PostgreSQL 16 in Docker Compose. The rebuilt
image advanced `alembic_version` to `0003`; the seed script loaded the same
samples; and the API returned byte-identical 30 daily points and metrics.
`forecast_points` stores `predicted_cost`, `lower_bound` and `upper_bound` as
`bigint` micro-units. Counts before teardown were 1 run and 30 points. The stack
and volume were removed with `docker compose down -v`.

**Known limitations carried into Milestone 5**

- The models are deliberately simple baselines, not regression/ARIMA/exponential
  smoothing. There is no trend, holiday calendar or exogenous driver.
- A 14-day holdout yields a noisy error estimate; a 90% empirical interval from
  14 residuals projected over 30 days is indicative, not calibrated.
- Calendar gaps are zero spend. Late or restated exports can change the history
  and therefore future forecasts; runs are snapshots.
- Confidence is a deterministic rule, not a probability.
- MAPE is undefined when every holdout actual is zero and excludes zero-actual
  days otherwise.
- Forecast values are clamped at zero, so negative net-spend days are not
  projected.
- Only daily granularity exists; no FX and no combined currency totals.
- No approval workflow or export yet (Milestone 6).

### Milestone 5 — AI advisor — `PLANNED`

- Provider adapter: OpenAI-compatible client for free-tier APIs (Groq documented
  default; Gemini, OpenRouter and local Ollama interchangeable via `.env`).
  Optional and disabled by default; no paid API and no key committed.
- Configuration: `CLOUDPILOT_LLM_ENABLED`, `CLOUDPILOT_LLM_BASE_URL`,
  `CLOUDPILOT_LLM_MODEL`, `CLOUDPILOT_LLM_API_KEY`. A missing key or a disabled
  flag falls back to the deterministic explanation.
- Only a bounded, redacted evidence package leaves the machine; raw billing files
  are never sent.
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
| POST | `/api/analysis/run` | Deterministic waste detection over a scope |
| GET | `/api/findings` | Findings from the latest run (or `run_id`) |
| GET | `/api/findings/{id}` | Finding detail, evidence and savings scenario |
| GET | `/api/prices` | Sourced catalogue prices with provenance |
| GET | `/api/prices/{id}` | One price entry and its source |
| POST | `/api/forecasts/run` | Deterministic daily forecast with held-out evaluation |
| GET | `/api/forecasts` | Latest forecast run with points (or `run_id`) |
| GET | `/api/forecasts/{run_id}` | One forecast run with its daily points |

The remaining endpoints from guide §11 (AI advisor, approvals, exports) arrive in
their own milestones.

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
4. **LLM provider:** one OpenAI-compatible adapter for free-tier APIs (Groq
   documented default; Gemini, OpenRouter or local Ollama by configuration).
   Optional and disabled by default; no paid API and no key in the repository.
5. **Export priority:** Markdown + CSV first in Milestone 6, PDF later.
6. **Waste rules:** idle and rightsizing thresholds above; every threshold is a
   setting (`CLOUDPILOT_IDLE_*`, `CLOUDPILOT_RIGHTSIZE_*`,
   `CLOUDPILOT_MIN_OBSERVATION_DAYS`, `CLOUDPILOT_MIN_SAMPLES`,
   `CLOUDPILOT_ANALYSIS_COST_DAYS`, `CLOUDPILOT_MIN_MONTHLY_SAVINGS`).
7. **Synthetic catalogue:** the demo catalogue is labelled `is_synthetic=true`,
   uses `example.invalid` source URLs and is never presented as a vendor quote.
8. **No invented SKUs:** rightsizing requires an explicit billing `sku` and a
   catalogue `replacement_sku`. Otherwise the resource is skipped and disclosed.
