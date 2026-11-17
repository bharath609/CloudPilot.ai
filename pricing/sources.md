# Pricing provenance — CloudPilot AI

## Current state (Milestone 3)

The catalogue loader is implemented in `backend/app/services/prices.py` and reads
`pricing/catalogue/demo_prices.csv`. The shipped file is **synthetic demo data**:

- every row has `is_synthetic=true`;
- the source URL uses the reserved `example.invalid` host;
- the source name says "synthetic demo catalogue";
- the API and every finding expose the flag and a warning.

It is **not** an AWS, Azure or GCP price list and must never be presented as a
vendor quote. The four fabricated entries exist only so the rightsizing path can
be demonstrated and tested without network access.

## Catalogue columns

| Field | Requirement |
|---|---|
| `provider` | `aws`, `azure`, `gcp` or `sample` |
| `sku` | Explicit SKU / instance type / storage class identifier (never inferred) |
| `display_name` | Human-readable label |
| `service` | Vendor service name |
| `region` | Region the price applies to |
| `usage_unit` | Must match the billing unit for a price ratio (`Hrs`, `GB-Mo`, …) |
| `unit_price` | Exact positive decimal, stored as scaled `BIGINT` (6 dp) |
| `currency` | ISO 4217 code |
| `effective_from` / `effective_to` | Validity window; `effective_to` may be blank for open-ended |
| `replacement_sku` | Optional explicit smaller SKU used for rightsizing |
| `is_synthetic` | `true` for demo data; surfaced everywhere |
| `source_name` | Vendor page, export or catalogue name |
| `source_url` | Required `http(s)` URL |
| `source_retrieved_at` | Optional UTC timestamp when the value was captured |
| `notes` | Tiering, commitments, free-tier or other caveats |

Identity is `(provider, sku, region, currency, usage_unit, effective_from)`.
Re-running the loader updates descriptive fields idempotently.

## Rules

1. No price value may be produced by an LLM. The AI may explain a calculation
   that already exists; it may not supply missing numbers.
2. Savings estimates must show the price entry used, its source URL, source name
   and effective date (`finding.price_source`).
3. Prices in different currencies are never combined. Rightsizing requires the
   billing currency, region and usage unit to match exactly; there is no FX path.
4. A price is selected only when it is effective on the analysis cost-window end
   date. If it does not cover the whole window, confidence is downgraded and a
   warning is added.
5. A price with no `source_url`, a non-positive unit price, an unsupported
   provider or an invalid effective range is rejected by the loader.
6. A missing SKU or missing price produces **no finding**. The run reports the
   skip; it never guesses a fallback SKU or price.
7. Negotiated discounts, commitments and free tiers are not modelled. Catalogue
   values are list prices.

## Replacing the demo catalogue

1. Add a real CSV under `pricing/catalogue/` using the columns above.
2. Set `CLOUDPILOT_PRICE_CATALOGUE_PATH` to that file.
3. Run `python scripts/seed_sample_data.py` (or call the loader from a small
   script) against the target database.
4. Confirm via `GET /api/prices` that `synthetic_count` is `0` and that every row
   has the intended source URL and effective dates.

Do not commit proprietary or paywalled price exports without permission.
