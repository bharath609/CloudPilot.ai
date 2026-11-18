import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { Decision, Finding } from "../api/types";
import { AppStateProvider } from "../state/AppState";
import { filtersFixture, healthFixture } from "../test/mockApi";
import { FindingsPage } from "./FindingsPage";

const finding: Finding = {
  id: 7,
  run_id: 3,
  finding_type: "idle_resource",
  status: "open",
  provider: "aws",
  account_id: "demo-aws-account-001",
  service: "Amazon EC2",
  resource_id: "i-demo-0a1b2c3d4e60",
  region: "eu-west-1",
  environment: "staging",
  project: "checkout-platform",
  currency: "USD",
  current_sku: "demo.ec2.c5.2xlarge",
  recommended_sku: null,
  baseline_monthly_cost: "4.552105",
  proposed_monthly_cost: "0.000000",
  estimated_monthly_savings: "4.552105",
  savings_pct: "100.000",
  confidence: "high",
  risk: "low",
  cost_window_start: "2026-01-31",
  cost_window_end: "2026-03-01",
  observation_start: "2026-01-31T00:00:00+00:00",
  observation_end: "2026-03-01T23:00:00+00:00",
  observation_days: 30,
  sample_count: 720,
  metrics: { cpu_avg_pct: "2.501", cpu_p95_max_pct: "9.958" },
  evidence: { metric_ids: ["metric-1"], notes: [] },
  assumptions: ["Billing rows are complete for the cost window."],
  warnings: [],
  price_source: { source_name: "CloudPilot synthetic demo catalogue", is_synthetic: true },
  uses_synthetic_prices: true,
  created_at: "2026-03-01T12:00:00+00:00",
  scenario: {
    id: 11,
    method: "stop_resource",
    currency: "USD",
    baseline_monthly_cost: "4.552105",
    proposed_monthly_cost: "0.000000",
    estimated_monthly_savings: "4.552105",
    assumptions: ["Resource is idle in the observation window."],
  },
  decision: null,
};

const decision: Decision = {
  id: 1,
  finding_id: 7,
  decision: "approve",
  actor: "alice",
  note: "Verified with owner",
  created_at: "2026-03-01T13:00:00+00:00",
};

function json(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

describe("FindingsPage decision workflow", () => {
  it("records an append-only decision and refreshes the finding", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    let decided = false;

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        if (url.includes("/api/filters")) return json(filtersFixture);
        if (url.includes("/api/health")) return json(healthFixture);
        if (url.includes("/api/findings/7/decision") && init?.method === "POST") {
          decided = true;
          return json(decision, 201);
        }
        if (url.includes("/api/findings")) {
          return json({
            run: null,
            items: [{ ...finding, decision: decided ? decision : null }],
            total: 1,
            limit: 50,
            offset: 0,
          });
        }
        return json({ error: { code: "not_found", message: url } }, 404);
      }),
    );

    render(
      <MemoryRouter>
        <AppStateProvider>
          <FindingsPage />
        </AppStateProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("i-demo-0a1b2c3d4e60")).toBeInTheDocument();
    expect(screen.getByText("Synthetic price")).toBeInTheDocument();
    expect(screen.getAllByText("4.55 USD").length).toBeGreaterThan(0);
    expect(screen.getByText("Pending review")).toBeInTheDocument();
    expect(
      screen.getByText(/Append-only: a newer decision supersedes this one/),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/reviewer label/i), {
      target: { value: "alice" },
    });
    fireEvent.change(screen.getByLabelText(/note \(optional\)/i), {
      target: { value: "Verified with owner" },
    });
    fireEvent.click(screen.getByRole("button", { name: /record decision/i }));

    expect(await screen.findByText(/by alice/)).toBeInTheDocument();

    await waitFor(() => {
      const post = calls.find(
        (call) => call.init?.method === "POST" && call.url.includes("/decision"),
      );
      expect(post).toBeDefined();
      expect(JSON.parse(String(post?.init?.body))).toEqual({
        decision: "approve",
        actor: "alice",
        note: "Verified with owner",
      });
    });

    // The finding total is unchanged; only a new decision row was appended.
    expect(screen.getAllByText("4.55 USD").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Approved").length).toBeGreaterThan(0);
  });
});
