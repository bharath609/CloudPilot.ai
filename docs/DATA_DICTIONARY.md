# CloudPilot AI — Data Dictionary

Version 1.3 — covers Milestones 1–5 (imports, cost records, utilization
metrics, validation issues, price catalogue, analysis runs, findings, savings
scenarios, forecasts and advisor reports). Money fields are `decimal.Decimal` in
Python and stored exactly as scaled integers (see §5). All timestamps are UTC.

---

## 1. Billing CSV contract

File: UTF-8 (BOM allowed), comma-delimited, header row required.
Machine-readable copy: `data/schemas/billing.schema.json`.

| Column | Type | Required | Rules | Example |
|---|---|---|---|---|
| `usage_date` | ISO date | yes | `YYYY-MM-DD`, between `2000-01-01` and tomorrow (UTC) | `2026-03-14` |
| `provider` | enum | yes | `aws`, `azure`, `gcp`, `sample` (case-insensitive, stored lowercase) | `aws` |
| `account_id` | string | yes | 3–64 chars `[A-Za-z0-9_*\-]`; 12-digit values are masked to `****1234` with a warning | `demo-aws-account-001` |
| `service` | string | yes | 1–80 chars, trimmed | `Amazon EC2` |
| `resource_id` | string | yes | 1–200 chars; unique per resource; no whitespace-only | `i-demo-0a1b2c3d4e5f` |
| `region` | string | yes | 1–64 chars | `eu-west-1` |
| `environment` | enum | yes | `dev`, `test`, `staging`, `prod`, `unknown`; blank → `unknown` | `prod` |
| `project` | string | yes | 1–120 chars; blank → `unassigned` | `checkout-platform` |
| `usage_quantity` | decimal | yes | ≥ 0, ≤ 1e15, up to 6 dp | `744` |
| `usage_unit` | string | yes | 1–32 chars matching `[A-Za-z0-9][A-Za-z0-9 _./-]*`; known set is a warning, not an error | `Hrs` |
| `cost_amount` | decimal | yes | ≥ 0, ≤ 1e12, up to 6 dp; no `NaN`/`Inf`; negatives are errors (credits arrive in a later milestone) | `142.567200` |
| `currency` | ISO 4217 | yes | Uppercase 3 letters, must be in allowlist (`USD,EUR,GBP,INR,CAD,AUD` by default) | `USD` |
| `tag_team` | string | yes | 1–80 chars; blank → `untagged` (also emitted as a warning) | `platform` |
| `tag_owner` | string | yes | 1–120 chars; blank → `unassigned` | `team-platform@example.test` |
| `sku` | string | no | Optional 1–120 chars. Links the row to a sourced catalogue price; never inferred. Absence is not a warning. | `demo.ec2.c5.2xlarge` |

Unknown extra columns are accepted, preserved in `cost_records.raw_json`, and
ignored by analytics. The documented optional columns (`sku`) are accepted
without an `unexpected_column` warning. Duplicate header names are a structural
error.

**Business key (duplicate detection):**
`usage_date + provider + account_id + service + resource_id + usage_unit + cost_amount`

Within one file, a repeated business key is an error and only the first row is
kept. A key that already exists in an earlier import is a warning only
(see ADR-007 and the plan's open question 3).

---

## 2. Utilization CSV contract

File: UTF-8 (BOM allowed), comma-delimited, header row required.
Machine-readable copy: `data/schemas/utilization.schema.json`.

| Column | Type | Required | Rules | Example |
|---|---|---|---|---|
| `timestamp` | ISO 8601 datetime | yes | `YYYY-MM-DDTHH:MM:SS[Z|±HH:MM]`, between `2000-01-01` and tomorrow; naive values treated as UTC | `2026-03-14T13:00:00Z` |
| `resource_id` | string | yes | 1–200 chars | `i-demo-0a1b2c3d4e5f` |
| `cpu_avg_pct` | decimal | yes | 0–100, up to 3 dp | `3.412` |
| `cpu_p95_pct` | decimal | yes | 0–100; if `< cpu_avg_pct`, warning `p95_below_average` | `5.870` |
| `memory_avg_pct` | decimal | yes | 0–100 | `18.200` |
| `memory_p95_pct` | decimal | yes | 0–100; same consistency warning | `22.450` |
| `network_in_bytes` | integer | yes | ≥ 0, ≤ 1e15 | `1048576` |
| `network_out_bytes` | integer | yes | ≥ 0, ≤ 1e15 | `524288` |
| `storage_used_pct` | decimal | yes | 0–100 | `41.000` |
| `sample_window_minutes` | integer | yes | 1–10080 (one week) | `60` |

**Business key (duplicate detection):** `resource_id + timestamp`.

Unknown `resource_id` values (not present in any billing import) are accepted
with a single `resource_not_in_billing` warning per distinct resource ID. Import
order is therefore irrelevant.

Low utilization is **not** a finding by itself. It is evidence for the
Milestone 3 rule engine, which adds observation windows, price provenance and
owner review.

---

## 3. Enumerations

| Name | Values |
|---|---|
| `ImportKind` | `billing`, `utilization` |
| `ImportStatus` | `valid`, `valid_with_warnings`, `partial`, `invalid`, `failed` |
| `Provider` | `aws`, `azure`, `gcp`, `sample` |
| `Environment` | `dev`, `test`, `staging`, `prod`, `unknown` |
| `Severity` | `error`, `warning` |
| `FindingType` | `idle_resource`, `over_provisioned` |
| `FindingStatus` | `open` |
| `RiskLevel` | `low`, `medium`, `high` |
| `ConfidenceLevel` | `low`, `medium`, `high` |
| `ScenarioMethod` | `stop_resource`, `rightsize_sku` |
| `ForecastMethod` | `seasonal_naive`, `moving_average` |
| `ForecastGranularity` | `day` |
| `ValidationCode` | see §6 |

---

## 4. Database tables

Column types below are logical; see §5 for physical storage.

### 4.1 `imports`

One row per upload attempt. Generalized from the guide's `billing_imports`.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `kind` | enum text | `billing` / `utilization` |
| `filename` | text(255) | basename only; path components stripped |
| `content_sha256` | char(64) | exact-duplicate detection |
| `content_bytes` | integer | upload size |
| `provider` | text(32), nullable | billing only; mixed providers → `mixed` |
| `status` | enum text | see §3 |
| `row_count` | integer | non-blank data rows parsed |
| `accepted_row_count` | integer | persisted rows |
| `rejected_row_count` | integer | rows with ≥1 error |
| `warning_count` | integer | warning issues emitted |
| `currencies` | JSON | distinct ISO codes found (billing) |
| `period_start` | date, nullable | min `usage_date` / `timestamp` date |
| `period_end` | date, nullable | max date |
| `source` | text(32) | `upload` (seed script sets `sample`) |
| `stats` | JSON | timing, extra counts, `truncated_issues`, `masks_applied` |
| `created_at` | timestamptz | |

### 4.2 `cost_records`

Normalized billing rows. Append-only.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `import_id` | FK → `imports.id` | indexed, `ON DELETE RESTRICT` |
| `source_row_number` | integer | data row in the original file |
| `usage_date` | date | indexed with provider |
| `provider` | text(16) | |
| `account_id` | text(64) | masked when required |
| `service` | text(80) | indexed |
| `resource_id` | text(200) | indexed |
| `region` | text(64) | |
| `environment` | enum text | |
| `project` | text(120) | |
| `quantity` | decimal(20,6) | from `usage_quantity` |
| `usage_unit` | text(32) | |
| `amount` | decimal(20,6) | money, exact |
| `currency` | char(3) | |
| `sku` | text(120), nullable | optional provider SKU; indexed |
| `tags` | JSON | `{team, owner, ...extra non-core columns}` |
| `raw_json` | JSON | original CSV row for auditability |
| `created_at` | timestamptz | |

Indexes: `(usage_date)`, `(provider, usage_date)`, `(service)`, `(resource_id)`,
`(import_id)`, `(currency, usage_date)`.

### 4.3 `resource_metrics`

Normalized utilization rows. Append-only.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `import_id` | FK → `imports.id` | indexed |
| `source_row_number` | integer | |
| `resource_id` | text(200) | indexed with timestamp |
| `observed_at` | timestamptz | |
| `cpu_avg_pct` | decimal(6,3) | 0–100 |
| `cpu_p95_pct` | decimal(6,3) | 0–100 |
| `memory_avg_pct` | decimal(6,3) | 0–100 |
| `memory_p95_pct` | decimal(6,3) | 0–100 |
| `network_in_bytes` | bigint | |
| `network_out_bytes` | bigint | |
| `storage_used_pct` | decimal(6,3) | 0–100 |
| `sample_window_minutes` | integer | 1–10080 |
| `created_at` | timestamptz | |

Unique constraint: `(resource_id, observed_at)`.

### 4.4 `import_issues`

Row-level validation output, also used for structural errors (`row_number=0`).

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `import_id` | FK → `imports.id` | indexed |
| `row_number` | integer | 0 = file/structural issue |
| `column` | text(64), nullable | offending column, if any |
| `code` | text(64) | machine-readable, §6 |
| `severity` | enum text | `error` / `warning` |
| `message` | text(500) | human-readable, never includes secrets |
| `raw_value` | text(200) | truncated original value |
| `created_at` | timestamptz | |

### 4.5 `price_entries`

Sourced unit prices, loaded from `pricing/catalogue/*.csv`. Never fetched from a
cloud provider and never generated by an LLM.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `provider` | text(16) | `aws` / `azure` / `gcp` / `sample` |
| `sku` | text(120) | provider/instance identifier, indexed with provider |
| `display_name` | text(160) | human-readable label |
| `service` | text(80) | |
| `region` | text(64) | price is region-specific |
| `usage_unit` | text(32) | must match the billing unit for a ratio |
| `unit_price` | decimal(20,6) | exact positive price |
| `currency` | char(3) | |
| `effective_from` / `effective_to` | date / nullable date | half-open validity window |
| `replacement_sku` | text(120), nullable | explicit smaller SKU; no inference |
| `is_synthetic` | boolean | true for demo data; surfaced in every response |
| `source_name` | text(200) | e.g. vendor pricing page or export name |
| `source_url` | text(500) | required `http(s)` URL |
| `source_retrieved_at` | timestamptz, nullable | when the value was captured |
| `notes` | text(1000), nullable | tiering, commitments, caveats |
| `created_at` / `updated_at` | timestamptz | loader upserts by identity |

Unique identity: `(provider, sku, region, currency, usage_unit, effective_from)`.

### 4.6 `analysis_runs`

One immutable record per `POST /api/analysis/run`.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `status` | text(16) | currently `completed` |
| `reference_date` | date | latest billing date in scope |
| `cost_window_start` / `cost_window_end` | date | inclusive 30-day default window |
| `currency` | char(3), nullable | optional scope filter |
| `filters` | JSON | provider/account/service/region/environment/project |
| `rule_config` | JSON | exact thresholds and business key used |
| `finding_count` | integer | |
| `total_savings_by_currency` | JSON | decimal strings; never combined |
| `uses_synthetic_prices` | boolean | true when any finding used demo prices |
| `notes` | JSON | scope, limitations and skipped-resource disclosure |
| `stats` | JSON | evaluated/skipped counts and duplicate rows excluded |
| `duration_ms` | integer | |
| `created_at` / `completed_at` | timestamptz | |

### 4.7 `findings`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `run_id` | FK → `analysis_runs.id` | `ON DELETE CASCADE` |
| `finding_type` | enum text | `idle_resource` / `over_provisioned` |
| `status` | enum text | `open` |
| `provider`, `account_id`, `service`, `resource_id`, `region`, `environment`, `project` | text | resource identity copied from billing |
| `currency` | char(3) | one currency per finding |
| `current_sku` / `recommended_sku` | text(120), nullable | rightsizing only |
| `baseline_monthly_cost` | decimal(20,6) | de-duplicated billing in the cost window |
| `proposed_monthly_cost` | decimal(20,6) | 0 for idle; price-ratio for rightsizing |
| `estimated_monthly_savings` | decimal(20,6) | baseline − proposed |
| `savings_pct` | decimal(6,3) | 3 dp |
| `confidence` | enum text | coverage of the cost window by observations |
| `risk` | enum text | prod idle = high; other values per environment |
| `cost_window_start` / `cost_window_end` | date | |
| `observation_start` / `observation_end` | timestamptz, nullable | |
| `observation_days` / `sample_count` | integer | minimum 14 days and 24 samples |
| `metrics` | JSON | CPU/memory averages and maxima used by the rule |
| `evidence` | JSON | capped cost-record IDs, metric IDs, counts and import IDs |
| `assumptions` | JSON | explicit arithmetic and scope |
| `warnings` | JSON | owner review, synthetic data, modelling limits |
| `price_source` | JSON | current/replacement price provenance (rightsizing) |
| `uses_synthetic_prices` | boolean | |
| `created_at` | timestamptz | |

### 4.8 `savings_scenarios`

One reproducible scenario per finding.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `finding_id` | FK → `findings.id` | `ON DELETE CASCADE` |
| `method` | enum text | `stop_resource` / `rightsize_sku` |
| `currency` | char(3) | |
| `baseline_monthly_cost` | decimal(20,6) | copied from the finding |
| `proposed_monthly_cost` | decimal(20,6) | |
| `estimated_monthly_savings` | decimal(20,6) | |
| `assumptions` | JSON | same assumptions shown on the finding |
| `created_at` | timestamptz | |

### 4.9 `forecast_runs`

One immutable record per `POST /api/forecasts/run`.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `status` | text(16) | `completed` |
| `method` | enum text | `seasonal_naive` / `moving_average` |
| `granularity` | enum text | `day` |
| `reference_date` | date | Latest de-duplicated billing date in scope |
| `history_start` / `history_end` | date | History actually used (≤ 365 days) |
| `horizon_start` / `horizon_end` | date | Inclusive projected window |
| `currency` | char(3), nullable | Set only when the request scoped one currency |
| `filters` | JSON | Applied scope fields |
| `config` | JSON | Horizon, holdout, method, window, quantile, minimums, business key |
| `series_count` | integer | Currencies successfully forecast |
| `evaluation` | JSON | Per-currency metrics and notes, keyed by ISO currency |
| `stats` | JSON | Row counts, duplicate exclusions, skipped series, sample flag |
| `notes` / `warnings` | JSON | Explicit assumptions and limitations |
| `duration_ms` | integer | Wall-clock runtime |
| `created_at` / `completed_at` | timestamptz | |

### 4.10 `forecast_points`

One predicted day per currency per run.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `run_id` | FK → `forecast_runs.id` | `ON DELETE CASCADE` |
| `currency` | char(3) | Series currency; never merged |
| `period` | date | One calendar day |
| `predicted_cost` | decimal(20,6) | Point forecast, clamped at zero |
| `lower_bound` | decimal(20,6) | Predicted − empirical interval width, clamped at zero |
| `upper_bound` | decimal(20,6) | Predicted + interval width |
| `method` | enum text | Copied from the run |
| `created_at` | timestamptz | |

### 4.11 `advisor_reports`

One immutable record per `POST /api/reports/generate`. It stores both the exact
bounded package that was eligible to leave the machine and the validated output
(or deterministic fallback).

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `status` | varchar(16) | `completed` when AI output was accepted, else `fallback` |
| `mode` | varchar(16) | `llm` or `deterministic` |
| `ai_used` | boolean | True only after schema, evidence-ID and numeric validation |
| `provider` | varchar(64), null | Configured provider label when a call was attempted |
| `model` | varchar(120), null | Model name from the response, or configured model when attempted |
| `analysis_run_id` | FK → `analysis_runs.id`, null | `ON DELETE SET NULL` |
| `forecast_run_id` | FK → `forecast_runs.id`, null | `ON DELETE SET NULL` |
| `fallback_reason` | varchar(64), null | Machine-readable reason code (below) |
| `validation_errors` | json string[] | Up to 20 rejection details |
| `evidence_sha256` | char(64) | SHA-256 of the canonical serialized package |
| `evidence` | json object | Bounded, redacted package; no raw CSV bytes or tags |
| `output` | json object | Validated typed output or deterministic fallback |
| `notes` | json string[] | Provenance/validation notes |
| `warnings` | json string[] | Human review and synthetic-data warnings |
| `attempts` | integer | Provider attempts used (0 when no call) |
| `latency_ms` | integer | Last provider call latency (0 when no call) |
| `duration_ms` | integer | Total report runtime |
| `created_at` / `completed_at` | timestamptz | |

No money column exists in this table: amounts inside `evidence`/`output` are
mirrored strings from the deterministic records, so the advisor cannot introduce
or alter a stored cost.

---

## 5. Exact money storage (ADR-002)

SQLite has no decimal type; `Numeric` there is a float and loses cents. All
decimal columns therefore use a `ScaledDecimal` type decorator backed by
`BIGINT`:

```
stored = round(value × 10^scale)      # Decimal → int, exact
value  = Decimal(stored) × 10^-scale  # int → Decimal, exact
```

| Column | Scale | Precision |
|---|---|---|
| `cost_records.amount` | 6 | 6 dp, ≤ 1e12 |
| `cost_records.quantity` | 6 | 6 dp |
| `resource_metrics.*_pct` | 3 | 3 dp |
| `price_entries.unit_price` | 6 | 6 dp, positive |
| `findings.*_cost`, `savings_scenarios.*_cost` | 6 | 6 dp |
| `forecast_points.predicted_cost`, `lower_bound`, `upper_bound` | 6 | 6 dp |
| `findings.savings_pct` | 3 | 3 dp |

Consequences:

- `SUM()` in SQL is integer addition → exact for any dialect.
- Values are quantized on write, so `0.1 + 0.2` round-trips as `0.3`.
- Inputs with more than 6 decimal places (3 for percentages) are rounded
  HALF_UP before storage. CSV values are otherwise never coerced to floats.
- Analytics must convert at the boundary: `Decimal(scaled) / Decimal(10**6)`.
- Currency conversion is not implemented and must not be attempted implicitly.

### 5.1 Analytics response fields (Milestone 2)

| Field | Type | Meaning |
|---|---|---|
| `window.start` / `window.end` | ISO date | Inclusive usage-date window actually applied |
| `window.days` | integer | `end - start + 1`, or `null` when no bound is known |
| `totals[].currency` | ISO 4217 | Currency of that total; never merged with another |
| `totals[].amount` | decimal string | Exact sum of `cost_records.amount`, 6 dp |
| `totals[].row_count` | integer | De-duplicated rows contributing to the total |
| `row_count` | integer | Sum of `totals[].row_count` across currencies |
| `excluded_duplicate_rows` | integer | Stored rows skipped because their business key already existed |
| `import_ids` | integer[] | Imports that contributed at least one counted row |
| `contains_sample_data` | boolean | True when any contributing import has `source = sample` |
| `dimension` | enum | `service`, `project`, `region`, `environment`, `provider`, `account`, `resource` |
| `items[].key` | string | Dimension value for this row |
| `items[].share_pct` | decimal string | Share of **that currency's** total, 3 dp, HALF_UP |
| `total_groups` | integer | Groups before the per-currency `limit` |
| `items_truncated` | boolean | True when `items` was cut by `limit` |
| `points[].bucket` | string | `YYYY-MM-DD` for daily, `YYYY-MM` for monthly |
| `granularity` | enum | `day` or `month` |

De-duplication key (identical to the importer's business key):

```
usage_date + provider + account_id + service + resource_id + usage_unit + amount
```

The earliest stored row (`MIN(id)`) wins. Re-imported rows remain in
`cost_records` for audit and appear in `/api/imports/{id}/records`; they are
excluded only from analytics.

`unit_price` / FX rates do not exist in the analytics path. No price or exchange
rate is inferred, looked up or generated for spend totals.

### 5.2 Analysis response fields (Milestone 3)

| Field | Type | Meaning |
|---|---|---|
| `run.reference_date` | ISO date | Latest billing date in the analysis scope |
| `run.cost_window_start` / `end` | ISO date | Inclusive cost window (30 days by default) |
| `run.rule_config` | object | Exact thresholds, minimums and de-duplication key |
| `run.total_savings_by_currency` | object | Decimal strings per ISO currency; never combined |
| `run.uses_synthetic_prices` | boolean | True when any finding used a synthetic price |
| `run.stats.skipped` | object | Counts of resources skipped (no utilization, missing SKU/price, mixed currency, …) |
| `finding.finding_type` | enum | `idle_resource` or `over_provisioned` |
| `finding.baseline_monthly_cost` | decimal string | De-duplicated imported billing in the window |
| `finding.proposed_monthly_cost` | decimal string | 0 for idle; billing × price ratio for rightsizing |
| `finding.estimated_monthly_savings` | decimal string | Exact baseline − proposed |
| `finding.confidence` | enum | Observation coverage: ≥90% high, ≥60% medium, else low |
| `finding.risk` | enum | Operating risk of the proposed change |
| `finding.observation_days` / `sample_count` | integer | Utilization evidence coverage |
| `finding.metrics` | object | CPU/memory values that triggered the rule |
| `finding.evidence` | object | Capped cost-record and metric IDs, counts, import IDs |
| `finding.assumptions` / `warnings` | string[] | Explicit reasoning and review requirements |
| `finding.price_source` | object | Current and replacement price provenance (rightsizing) |
| `finding.uses_synthetic_prices` | boolean | True when demo prices were used |
| `finding.scenario` | object | Stored `stop_resource` / `rightsize_sku` arithmetic |

Rightsizing arithmetic:

```
proposed = baseline × replacement.unit_price / current.unit_price
savings  = baseline − proposed
```

Both prices must have the same `provider`, `region`, `currency` and `usage_unit`,
and both must be effective on the cost-window end date. If either is missing, no
finding is produced and the run reports the skip. No fallback price is guessed.

### 5.3 Forecast response fields (Milestone 4)

| Field | Type | Meaning |
|---|---|---|
| `run.reference_date` | ISO date | Latest de-duplicated billing date in scope |
| `run.history_start` / `history_end` | ISO date | History actually used, capped at `forecast_max_history_days` |
| `run.horizon_start` / `horizon_end` | ISO date | Inclusive projected window |
| `run.config` | object | Method, horizon, holdout, window, season length, quantile, minimums, business key |
| `run.evaluation` | object | Per-currency metrics, keyed by currency |
| `run.stats.skipped` | object | Currency → reason (`insufficient_history`, `holdout_too_long`, …) |
| `run.stats.daily_groups` / `stored_cost_rows` | integer | Grouped currency-days used / de-duplicated billing rows in scope |
| `run.stats.duplicate_rows_excluded` | integer | Stored rows skipped by the business key |
| `series[].history_days` | integer | Calendar days in history, including zero-spend gaps |
| `series[].projected_total` | decimal string | Exact sum of daily point forecasts for that currency |
| `series[].projected_lower` / `upper` | decimal string | Exact sums of daily bounds, not a simultaneous interval |
| `evaluation.mae` / `rmse` | decimal string | Held-out error, same currency units |
| `evaluation.bias` | decimal string | Mean signed error (actual − predicted); negative means over-forecast |
| `evaluation.mape_pct` | decimal string or null | Mean absolute percentage error, 3 dp; excludes zero actuals |
| `evaluation.mape_excluded_points` | integer | Holdout days excluded from MAPE because actual spend was zero |
| `evaluation.interval_quantile` | decimal string | Residual quantile used (default `0.90`) |
| `evaluation.interval_width` | decimal string | Empirical absolute-residual width applied to each day |
| `evaluation.confidence` | enum | `high` / `medium` / `low` by history length and MAPE |
| `evaluation.warnings` | string[] | Short history/holdout, MAPE unavailable, degenerate interval, horizon > holdout, flat average |
| `points[].period` | ISO date | One calendar day |
| `points[].predicted_cost` | decimal string | Clamped at zero |
| `points[].lower_bound` / `upper_bound` | decimal string | Predicted ± width, lower clamped at zero |

Forecast arithmetic:

```
seasonal_naive: forecast[d] = actual[d - 7] (recursively for d beyond the last actual)
moving_average: forecast[d] = mean(last N actual days)  (flat)
MAE  = mean(|actual - predicted|) over the holdout
RMSE = sqrt(mean((actual - predicted)^2)) over the holdout
bias = mean(actual - predicted) over the holdout
MAPE = mean(|actual - predicted| / actual) × 100, excluding actual = 0
width = empirical q-quantile of |actual - predicted| over the holdout
```

No FX is applied. Each currency is forecast and totalled separately; the response
contains no combined total.

### 5.4 Advisor report fields (Milestone 5)

| Field | Type | Meaning |
|---|---|---|
| `status` | enum | `completed` (AI accepted) or `fallback` |
| `mode` | enum | `llm` or `deterministic` |
| `ai_used` | boolean | True only when the model answer passed every check |
| `provider` / `model` | string or null | Provider label / returned model, when a call was attempted |
| `analysis_run_id` / `forecast_run_id` | integer or null | Immutable inputs used for the package |
| `fallback_reason` | string or null | Why deterministic output was used (table below) |
| `validation_errors` | string[] | Concrete rejections, e.g. `Unsupported numeric claim: $999.99` |
| `evidence_sha256` | hex string | SHA-256 of canonical `evidence` JSON (`sort_keys`, no spaces) |
| `output.executive_summary` | string | Prose grounded in the package |
| `output.priority_findings[].finding_id` | `finding-N` | Must exist in the package |
| `output.priority_findings[].evidence_ids` | string[] | `cost-N`, `metric-N`, `price-N`, `import-N`, `forecast-N`, `finding-N`; all must exist |
| `output.priority_findings[].risk` | enum | `low` / `medium` / `high` |
| `output.priority_findings[].assumptions` | string[] | At least one; no new numbers beyond the package |
| `output.unknowns` | string[] | Missing context the model or fallback surfaced |
| `output.human_review_required` | literal `true` | Enforced by the schema |
| `evidence` | object | The exact redacted package sent or eligible to be sent |
| `notes` / `warnings` | string[] | Whether data left the machine, synthetic-data notice, omissions |

Fallback reason codes:

| Code | Meaning |
|---|---|
| `disabled` | `CLOUDPILOT_LLM_ENABLED` is false (default); no network call |
| `missing_api_key` | Advisor enabled but no key configured; no network call |
| `insecure_transport` | Base URL is not HTTPS or localhost HTTP; call blocked |
| `provider_error` | Non-retryable HTTP status or connection failure |
| `timeout` | Request timed out after bounded retries |
| `invalid_json` | Assistant content was not a JSON object |
| `schema_invalid` | JSON did not match the required Pydantic schema |
| `unknown_finding_id` | Cited a finding not present in the package |
| `unknown_evidence_id` | Cited evidence not present in the package |
| `unsupported_numeric_claim` | Invented decimal, currency amount, percentage, magnitude word, or integer >31 absent from the package |
| `missing_priority_finding` | Package contained findings but the model returned none |
| `evidence_package_too_large` | Even the fully trimmed package exceeded the configured character limit |
| `invalid_response` / `response_too_large` | Provider payload malformed or above the byte cap |
| `validation_failed` | Any other validation rejection |

The fallback output is generated locally from the same package, always sets
`human_review_required=true`, and states that no cloud action was taken.

---

## 6. Validation codes

| Code | Severity | Meaning |
|---|---|---|
| `file_empty` | error | Zero bytes |
| `file_too_large` | error | Exceeds upload limit |
| `unsupported_file_type` | error | Not `.csv` |
| `invalid_encoding` | error | Not valid UTF-8 |
| `no_header` | error | Header row missing |
| `no_data_rows` | error | Header present but no data rows |
| `invalid_csv_structure` | error | CSV quoting/structure cannot be parsed |
| `duplicate_header` | error | Same column twice |
| `blank_header` | error | Empty column name |
| `missing_columns` | error | Required columns absent (lists them) |
| `row_field_count` | error | Row has more/fewer fields than header |
| `too_many_rows` | error | Exceeds row limit |
| `required` | error | Required value blank |
| `too_long` | error | Exceeds max length |
| `invalid_date` | error | Not ISO `YYYY-MM-DD` or out of allowed range |
| `invalid_timestamp` | error | Not ISO 8601 or out of allowed range |
| `invalid_number` | error | Not a finite decimal |
| `negative_number` | error | Value below zero |
| `number_out_of_range` | error | Above maximum / below minimum |
| `invalid_integer` | error | Not an integer |
| `invalid_provider` | error | Not an allowed provider |
| `invalid_environment` | error | Not an allowed environment |
| `invalid_currency` | error | Not a 3-letter ISO code |
| `currency_not_allowed` | error | Not in configured allowlist |
| `invalid_account_id` | error | Bad shape / characters |
| `invalid_resource_id` | error | Bad shape / characters |
| `invalid_unit` | error | Malformed `usage_unit` |
| `invalid_text` | error | Control characters in a text field |
| `unknown_unit` | warning | Unit not in known set |
| `duplicate_row` | error | Business key repeated in this file |
| `duplicate_existing_record` | warning (billing) / error (utilization) | Business key exists from an earlier import. Billing rows are stored with a warning for audit but excluded from analytics (earliest row wins); utilization rows are skipped because a duplicated sample would double-count |
| `p95_below_average` | warning | p95 < average, sample likely inconsistent |
| `resource_not_in_billing` | warning | Utilization resource has no billing rows |
| `account_id_masked` | warning | 12-digit account ID was masked before storage |
| `untagged_team` | warning | `tag_team` blank → `untagged` |
| `unowned_resource` | warning | `tag_owner` blank → `unassigned` |
| `mixed_currency` | warning | Import contains more than one currency |
| `issues_truncated` | warning | More issues than the configured cap |
| `unexpected_column` | warning | Extra column retained in `raw_json` only |
| `strict_mode_rejected` | error | Strict mode rejected the file because at least one row failed |
| `import_conflict` | error (HTTP 409) | Database unique constraint rejected the batch, e.g. a concurrent duplicate |

Codes are stable API surface; renaming requires a version bump.

---

## 7. Synthetic sample data

| File | Purpose | Expected result |
|---|---|---|
| `data/sample/billing_sample.csv` | 60 days × 8 resources, USD, all providers, optional `sku` for 3 EC2 resources | `valid` |
| `data/sample/utilization_sample.csv` | 30 days hourly × 4 resources | `valid` (possibly warnings) |
| `data/sample/billing_row_errors.csv` | Bad date, negative cost, bad currency, dupes, bad enum | `partial` with precise errors |
| `data/sample/billing_missing_column.csv` | Removes `cost_amount` | `invalid`, 0 rows |
| `data/sample/utilization_row_errors.csv` | Bad timestamp, >100 %, bad ints | `partial` |
| `data/sample/billing_multicurrency.csv` | USD + EUR | `valid_with_warnings` + `mixed_currency` |
| `pricing/catalogue/demo_prices.csv` | 4 clearly labelled synthetic prices | Loads idempotently; all `is_synthetic=true` |

All values are fabricated. Account IDs use `demo-` prefixes. The demo catalogue
uses `example.invalid` source URLs and is never a vendor price list.
