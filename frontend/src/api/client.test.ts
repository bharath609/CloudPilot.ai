import { describe, expect, it, vi } from "vitest";

import type { CostSummary } from "./types";
import { ApiError, api, exportUrl, queryString } from "./client";

function response(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

describe("queryString", () => {
  it("drops empty values and keeps false", () => {
    expect(
      queryString({
        a: 1,
        b: "",
        c: null,
        d: undefined,
        e: false,
        f: "USD",
      }),
    ).toBe("?a=1&e=false&f=USD");
  });

  it("returns an empty string when nothing remains", () => {
    expect(queryString({ a: "", b: undefined })).toBe("");
  });
});

describe("exportUrl", () => {
  it("builds download URLs under /api", () => {
    expect(exportUrl("/exports/findings.csv")).toBe("/api/exports/findings.csv");
    expect(exportUrl("/exports/summary.md", { run_id: 2 })).toBe(
      "/api/exports/summary.md?run_id=2",
    );
  });
});

describe("api client", () => {
  it("parses a successful payload", async () => {
    const payload: CostSummary = {
      window: { start: "2026-01-01", end: "2026-03-01", days: 60 },
      totals: [{ currency: "USD", amount: "1531.305850", row_count: 480 }],
      row_count: 480,
      excluded_duplicate_rows: 0,
      import_ids: [1],
      import_count: 1,
      contains_sample_data: false,
      notes: [],
    };
    const fetchMock = vi.fn(async () => response(payload));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.summary({ currency: "USD" })).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/costs/summary?currency=USD",
      expect.objectContaining({ headers: expect.objectContaining({ Accept: "application/json" }) }),
    );
  });

  it("surfaces the backend error envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        response(
          {
            error: {
              code: "invalid_date_range",
              message: "'start' must be on or before 'end'.",
              details: { start: "2026-03-02", end: "2026-03-01" },
            },
          },
          400,
        ),
      ),
    );

    try {
      await api.summary({ start: "2026-03-02", end: "2026-03-01" });
      throw new Error("expected the call to reject");
    } catch (caught) {
      expect(caught).toBeInstanceOf(ApiError);
      const error = caught as ApiError;
      expect(error.status).toBe(400);
      expect(error.code).toBe("invalid_date_range");
      expect(error.message).toContain("on or before");
      expect(error.details).toEqual({ start: "2026-03-02", end: "2026-03-01" });
    }
  });

  it("falls back to an HTTP message for a non-JSON error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 502,
        json: async () => {
          throw new SyntaxError("not json");
        },
      })),
    );

    await expect(api.health()).rejects.toMatchObject({
      status: 502,
      code: "http_502",
      message: "Request failed with HTTP 502.",
    });
  });

  it("uploads multipart form data without forcing a JSON content type", async () => {
    const fetchMock = vi.fn(async () => response({ id: 7 }, 201));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["usage_date,provider\n"], "billing.csv", { type: "text/csv" });

    await api.upload("billing", file);

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/imports/billing");
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });
});
