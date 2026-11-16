# CloudPilot AI — Data Dictionary

Version 1.0 — covers Milestone 1 (imports, cost records, utilization metrics,
validation issues). Money fields are `decimal.Decimal` in Python and stored
exactly as scaled integers (see §5). All timestamps are UTC.

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

Unknown extra columns are accepted, preserved in `cost_records.raw_json`, and
ignored by analytics. Duplicate header names are a structural error.

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

Low utilization is **not** a finding in Milestone 1. It is raw evidence for the
Milestone 3 rule engine, which adds observation windows, owner review and
workload-specific safeguards.

---

## 3. Enumerations

| Name | Values |
|---|---|
| `ImportKind` | `billing`, `utilization` |
| `ImportStatus` | `valid`, `valid_with_warnings`, `partial`, `invalid`, `failed` |
| `Provider` | `aws`, `azure`, `gcp`, `sample` |
| `Environment` | `dev`, `test`, `staging`, `prod`, `unknown` |
| `Severity` | `error`, `warning` |
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

`unit_price` / FX rates do not exist in this milestone. No price or exchange rate
is inferred, looked up or generated.

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
| `data/sample/billing_sample.csv` | 60 days × 8 resources, USD, all providers | `valid` |
| `data/sample/utilization_sample.csv` | 30 days hourly × 4 resources | `valid` (possibly warnings) |
| `data/sample/billing_row_errors.csv` | Bad date, negative cost, bad currency, dupes, bad enum | `partial` with precise errors |
| `data/sample/billing_missing_column.csv` | Removes `cost_amount` | `invalid`, 0 rows |
| `data/sample/utilization_row_errors.csv` | Bad timestamp, >100 %, bad ints | `partial` |
| `data/sample/billing_multicurrency.csv` | USD + EUR | `valid_with_warnings` + `mixed_currency` |

All values are fabricated. Account IDs use `demo-` prefixes.
