# Pricing provenance — CloudPilot AI

## Current state (Milestone 1)

There is **no price catalogue yet**. Milestone 1 only ingests, validates and
stores billing and utilization evidence. The amounts in `data/sample/*.csv` are
synthetic and must not be presented as vendor prices.

## Rules for Milestone 3 and beyond

Every row in `pricing/catalogue/` must carry:

| Field | Requirement |
|---|---|
| `provider` | `aws`, `azure` or `gcp` |
| `service` | Vendor service name |
| `region` | Region the price applies to |
| `sku` | SKU / instance type / storage class identifier |
| `unit` | Pricing unit (`Hrs`, `GB-Mo`, `Requests`, …) |
| `unit_price` | Exact decimal string, never a binary float |
| `currency` | ISO 4217 code |
| `effective_from` / `effective_to` | Validity window of the price |
| `source_url` | Public vendor pricing or export URL |
| `retrieved_at` | UTC timestamp when the value was captured |
| `notes` | Free-text caveats (tiering, free tier, commitments) |

Additional rules:

1. No price value may be produced by an LLM. The AI may explain a calculation
   that already exists; it may not supply missing numbers.
2. Savings estimates must show the price entry used, its source URL and its
   effective date.
3. Prices in different currencies are never combined without a documented FX
   source and conversion date.
4. Stale prices must be flagged when `retrieved_at` is older than a configured
   threshold.
5. A price with no `source_url` is rejected by the catalogue loader.

`catalogue/` is intentionally empty until Milestone 3. Keeping it empty is more
honest than shipping placeholder prices that could be mistaken for real data.
