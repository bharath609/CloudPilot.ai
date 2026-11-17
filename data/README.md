# Data — CloudPilot AI

## ⚠️ All sample data is synthetic

Every file under `data/sample/` is fabricated for demonstration and testing.
Account IDs use `demo-` prefixes, owners use `example.test` addresses, and prices
are invented. **Nothing here is a real cloud bill, real price or real customer
data.** The application cannot call any cloud provider.

## Files

| File | Rows | Purpose | Expected import result |
|---|---|---|---|
| `sample/billing_sample.csv` | 480 | 60 days × 8 resources across AWS, Azure and GCP, all USD; optional `sku` on 3 EC2 resources | `valid` |
| `sample/utilization_sample.csv` | 2,880 | 30 days of hourly samples for 4 resources | `valid` after billing; `valid_with_warnings` if billing is missing |
| `sample/billing_row_errors.csv` | 10 | Bad date, negative cost, bad currency/provider/environment, duplicate, missing field, NaN | `partial` (2 accepted, 8 rejected) |
| `sample/billing_missing_column.csv` | 1 | `cost_amount` removed | `invalid`, 0 rows stored |
| `sample/billing_multicurrency.csv` | 2 | USD + EUR | `valid_with_warnings` with `mixed_currency` |
| `sample/utilization_row_errors.csv` | 8 | Invalid timestamp, out-of-range percentages, negative value, non-integer, bad window, inconsistent p95 | `partial` (2 accepted, 6 rejected) |

Regenerate deterministically (fixed seed `20260101`):

```bash
python scripts/generate_sample_data.py
```

Load the clean sample into the configured database:

```bash
python scripts/seed_sample_data.py
```

The seed script also loads the synthetic price catalogue. Use `--no-prices` to
skip it or `--catalogue path/to/file.csv` to choose another catalogue.

## Contracts

- `schemas/billing.schema.json` — generic billing CSV row contract
- `schemas/utilization.schema.json` — generic utilization CSV row contract
- `../docs/DATA_DICTIONARY.md` — every field, rule, error code and table

CSV files must be UTF-8 (BOM tolerated), comma-delimited, with a header row and
the exact snake_case column names. Extra columns are retained in raw row data
but ignored by analytics.

## Currency assumptions

- The main sample contains **USD only**.
- The multi-currency fixture exists to prove the importer flags mixed currency.
- **No exchange rates are applied anywhere.** Currencies must be aggregated
  separately. A EUR total and a USD total are never added together.
- Currency conversion is not implemented and will require an explicit FX source,
  rate and conversion date before it is allowed.

## Pricing assumptions

The per-unit prices embedded in the generator are illustrative, not vendor
prices. `pricing/catalogue/demo_prices.csv` is also synthetic: every row is
marked `is_synthetic=true`, uses an `example.invalid` source URL and is exposed
as demo data by the API and findings. A real catalogue must supply a real source
URL, retrieval date and effective period (see `../pricing/sources.md`).

## Expected analysis result

With the sample data and demo catalogue loaded, `POST /api/analysis/run` returns
two idle resources and one rightsizing candidate. Total estimated savings are
USD `276.720019` for the 30-day window `2026-01-31..2026-03-01`. Every number is
recomputable from the CSV files with `Decimal` arithmetic. These are synthetic
sample findings, not a real savings claim.

## Privacy

Do not commit real billing exports. Account identifiers are masked when they
look like 12-digit account numbers, but service names, project names and owner
tags can still be sensitive. Use masked demo data until authentication and
encryption are implemented.
