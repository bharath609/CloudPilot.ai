# Data — CloudPilot AI

## ⚠️ All sample data is synthetic

Every file under `data/sample/` is fabricated for demonstration and testing.
Account IDs use `demo-` prefixes, owners use `example.test` addresses, and prices
are invented. **Nothing here is a real cloud bill, real price or real customer
data.** The application cannot call any cloud provider.

## Files

| File | Rows | Purpose | Result in the app's importer |
|---|---|---|---|
| `sample/billing_sample.csv` | 480 | 60 days × 8 resources across AWS, Azure and GCP, all USD | 480 accepted, 0 rejected (USD) |
| `sample/billing_multi_currency_sample.csv` | 240 | 120 EUR + 120 INR rows | 240 accepted (EUR 120, INR 120) |
| `sample/billing_multicurrency.csv` | 2 | One USD and one EUR row | 2 accepted (one per currency) |
| `sample/billing_row_errors.csv` | 10 | Bad date, bad amount, unsupported currency | 6 accepted, 4 rejected with line numbers |
| `sample/billing_missing_column.csv` | 1 | No cost column at all | File rejected: `Missing required column(s): amount` |
| `sample/utilization_sample.csv` | 2,880 | 30 days of hourly samples for 4 resources | 4 resources (latest snapshot per `resource_id`), 3 findings |
| `sample/utilization_multi_currency_sample.csv` | 2,880 | Same shape, multi-currency fixture | 4 resources (latest snapshot per `resource_id`) |
| `sample/utilization_row_errors.csv` | 8 | Invalid timestamp, out-of-range percentages | 1 accepted, 1 rejected |

## How to import

Open the installed app → **Imports**:

1. **Billing** needs `invoice_date, provider, service, amount, currency`. Everything
   else (`project, region, environment, resource_id, resource_type, usage_amount,
   unit, unit_price, sku`) is optional and gets a documented default.
2. **Resources** only needs `resource_id`. `name, resource_type, provider, region,
   environment, currency, cost_per_hour, cpu_pct, memory_pct, status, sku` are
   optional; missing cost or CPU columns produce an explicit warning in the report.
   Repeated rows for one `resource_id` collapse to the latest snapshot.
3. Choose **Replace current dataset** to drop the demo rows, or **Append** to add to
   what is already stored. **Dataset controls** restores the demo data at any time.

The sample files use export-style headers (`usage_date`, `cost_amount`,
`cpu_avg_pct`, …). The importer normalises these automatically, so the files in
this folder import without editing:

| Sample header | Canonical field |
|---|---|
| `usage_date` | `invoice_date` |
| `cost_amount`, `unblended_cost`, `cost` | `amount` |
| `currency_code` | `currency` |
| `cpu_avg_pct`, `cpu_avg` | `cpu_pct` |
| `memory_avg_pct`, `memory_avg` | `memory_pct` |
| `usage_quantity` | `usage_amount` |
| `usage_unit` | `unit` |
| `cloud_provider` | `provider` |

`schemas/billing.schema.json` and `schemas/utilization.schema.json` describe the
sample fixtures themselves (the export-style shape above), not the canonical
column names.

## Currency assumptions

- The main sample contains **USD only**; the multi-currency fixtures exist to prove
  that currencies are kept apart.
- **No exchange rates are applied anywhere.** A EUR total and a USD total are never
  added together, and switching currency in the UI switches the dataset.
- An imported row whose currency is not USD, EUR or INR is rejected with its line
  number rather than silently converted.

## Findings from imported inventory

Resource imports generate findings with two transparent thresholds: idle below 15%
CPU and rightsizing below 45% CPU. Monthly baselines are `cost_per_hour × 730` in
the same currency. The finding text states these assumptions and warns that the
snapshot came from a file, not a live cloud API.

## Privacy

Do not commit real billing exports. Account identifiers are masked when they look
like 12-digit account numbers, but service names, project names and owner tags can
still be sensitive. The desktop app stores imported data only in its local SQLite
file and sends nothing over the network.
