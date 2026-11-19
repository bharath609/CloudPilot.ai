import { vi } from "vitest";

import type {
  CostBreakdown,
  CostSummary,
  CostTrends,
  FilterOptions,
  FindingListResponse,
  ForecastListResponse,
  Health,
} from "../api/types";

export const healthFixture: Health = {
  status: "ok",
  app: "CloudPilot AI",
  version: "1.0.0",
  environment: "test",
  database: "ok",
  time: "2026-03-01T12:00:00+00:00",
};

export const filtersFixture: FilterOptions = {
  window_start: "2026-01-01",
  window_end: "2026-03-01",
  day_count: 60,
  currencies: ["USD"],
  providers: ["aws", "azure"],
  services: ["Amazon EC2", "Azure Virtual Machines"],
  regions: ["eu-west-1"],
  environments: ["dev", "prod"],
  projects: ["checkout-platform"],
  accounts: ["demo-aws-account-001"],
  import_count: 2,
  last_import_at: "2026-03-01T10:00:00+00:00",
  last_import_filename: "utilization_sample.csv",
  last_billing_date: "2026-03-01",
  contains_sample_data: true,
  synthetic_price_count: 4,
  notes: ["At least one import came from the synthetic sample seed."],
};

export const summaryFixture: CostSummary = {
  window: { start: "2026-01-01", end: "2026-03-01", days: 60 },
  totals: [{ currency: "USD", amount: "1531.305850", row_count: 480 }],
  row_count: 480,
  excluded_duplicate_rows: 0,
  import_ids: [1, 2],
  import_count: 2,
  contains_sample_data: true,
  notes: [],
};

export const breakdownFixture: CostBreakdown = {
  dimension: "service",
  window: { start: "2026-01-01", end: "2026-03-01", days: 60 },
  currency: "USD",
  totals: [{ currency: "USD", amount: "1531.305850", row_count: 480 }],
  items: [
    {
      key: "Amazon EC2",
      currency: "USD",
      amount: "896.430120",
      row_count: 300,
      share_pct: "58.540",
    },
  ],
  total_groups: 1,
  items_truncated: false,
  excluded_duplicate_rows: 0,
  notes: [],
};

function buckets(): string[] {
  const start = Date.UTC(2026, 0, 1);
  return Array.from({ length: 60 }, (_, index) =>
    new Date(start + index * 86_400_000).toISOString().slice(0, 10),
  );
}

export const trendsFixture: CostTrends = {
  granularity: "day",
  window: { start: "2026-01-01", end: "2026-03-01", days: 60 },
  currency: "USD",
  points: buckets().map((bucket, index) => ({
    bucket,
    currency: "USD",
    amount: index < 30 ? "20.000000" : "30.000000",
    row_count: 8,
  })),
  totals: [{ currency: "USD", amount: "1531.305850", row_count: 480 }],
  excluded_duplicate_rows: 0,
  notes: [],
};

export const findingsFixture: FindingListResponse = {
  run: null,
  items: [],
  total: 0,
  limit: 4,
  offset: 0,
};

export const forecastFixture: ForecastListResponse = {
  run: null,
  total: 1,
  series: [
    {
      currency: "USD",
      history_start: "2026-01-01",
      history_end: "2026-02-28",
      horizon_start: "2026-03-01",
      horizon_end: "2026-03-02",
      history_days: 59,
      points: [
        {
          period: "2026-03-01",
          predicted_cost: "25.500000",
          lower_bound: "20.000000",
          upper_bound: "31.000000",
        },
        {
          period: "2026-03-02",
          predicted_cost: "26.500000",
          lower_bound: "21.000000",
          upper_bound: "32.000000",
        },
      ],
      evaluation: {
        method: "seasonal_naive",
        history_days: 59,
        train_days: 45,
        holdout_days: 14,
        evaluated_points: 14,
        mae: "2.100000",
        rmse: "2.800000",
        bias: "-0.400000",
        mape_pct: "7.900",
        mape_excluded_points: 0,
        interval_quantile: "0.900",
        interval_width: "8.000000",
        confidence: "medium",
        warnings: [],
      },
      projected_total: "765.016323",
      projected_lower: "700.000000",
      projected_upper: "830.000000",
      notes: [],
    },
  ],
};

function json(data: unknown, status = 200): Promise<Response> {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
    headers: new Headers({ "content-type": "application/json" }),
  } as Response);
}

/** Installs a fetch double covering the endpoints used by the Overview page. */
export function installMockApi() {
  const fetchMock = vi.fn((input: RequestInfo | URL): Promise<Response> => {
    const url = String(input);
    if (url.includes("/api/health")) return json(healthFixture);
    if (url.includes("/api/filters")) return json(filtersFixture);
    if (url.includes("/api/costs/summary")) return json(summaryFixture);
    if (url.includes("/api/costs/breakdown")) return json(breakdownFixture);
    if (url.includes("/api/costs/trends")) return json(trendsFixture);
    if (url.includes("/api/findings")) return json(findingsFixture);
    if (url.includes("/api/forecasts")) return json(forecastFixture);
    return json({ error: { code: "not_found", message: url } }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
