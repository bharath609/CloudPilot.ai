/** Small typed API client with the backend's structured error envelope. */

import type {
  AdvisorReportDetail,
  AdvisorReportListResponse,
  AnalysisRunSummary,
  CostBreakdown,
  CostSummary,
  CostTrends,
  Decision,
  DecisionKind,
  DecisionListResponse,
  FilterOptions,
  Finding,
  FindingListResponse,
  ForecastListResponse,
  ForecastResult,
  Health,
  ImportDetail,
  ImportResult,
  PaginatedImports,
  PaginatedIssues,
  ResourceHealthResponse,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;

  constructor(message: string, status: number, code: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error.";
}

type QueryValue = string | number | boolean | null | undefined;

export function queryString(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function request<T>(
  path: string,
  init: RequestInit | undefined,
  signal?: AbortSignal,
): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    signal,
    headers: {
      Accept: "application/json",
      ...(isForm || !init?.body ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let code = `http_${response.status}`;
    let message = `Request failed with HTTP ${response.status}.`;
    let details: unknown;
    try {
      const payload = (await response.json()) as {
        error?: { code?: string; message?: string; details?: unknown };
        detail?: unknown;
      };
      if (payload.error) {
        code = payload.error.code ?? code;
        message = payload.error.message ?? message;
        details = payload.error.details;
      } else if (payload.detail) {
        message = typeof payload.detail === "string" ? payload.detail : message;
        details = payload.detail;
      }
    } catch {
      // Non-JSON error body: keep the status-based message.
    }
    throw new ApiError(message, response.status, code, details);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/health", undefined, signal),
  filters: (signal?: AbortSignal) => request<FilterOptions>("/filters", undefined, signal),

  summary: (params: Record<string, QueryValue>, signal?: AbortSignal) =>
    request<CostSummary>(`/costs/summary${queryString(params)}`, undefined, signal),
  breakdown: (
    params: Record<string, QueryValue> & { dimension: string; limit?: number },
    signal?: AbortSignal,
  ) => request<CostBreakdown>(`/costs/breakdown${queryString(params)}`, undefined, signal),
  trends: (
    params: Record<string, QueryValue> & { granularity?: string },
    signal?: AbortSignal,
  ) => request<CostTrends>(`/costs/trends${queryString(params)}`, undefined, signal),

  findings: (params: Record<string, QueryValue>, signal?: AbortSignal) =>
    request<FindingListResponse>(`/findings${queryString(params)}`, undefined, signal),
  finding: (id: number, signal?: AbortSignal) =>
    request<Finding>(`/findings/${id}`, undefined, signal),
  runAnalysis: (body: Record<string, unknown> = {}) =>
    request<{ run: AnalysisRunSummary; findings: Finding[] }>("/analysis/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  decisions: (params: Record<string, QueryValue>, signal?: AbortSignal) =>
    request<DecisionListResponse>(`/decisions${queryString(params)}`, undefined, signal),
  decide: (findingId: number, body: { decision: DecisionKind; actor: string; note?: string | null }) =>
    request<Decision>(`/findings/${findingId}/decision`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  resources: (params: Record<string, QueryValue>, signal?: AbortSignal) =>
    request<ResourceHealthResponse>(`/resources${queryString(params)}`, undefined, signal),

  latestForecast: (signal?: AbortSignal) =>
    request<ForecastListResponse>("/forecasts", undefined, signal),
  runForecast: (body: Record<string, unknown>) =>
    request<ForecastResult>("/forecasts/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  reports: (params: Record<string, QueryValue>, signal?: AbortSignal) =>
    request<AdvisorReportListResponse>(`/reports${queryString(params)}`, undefined, signal),
  report: (id: number, signal?: AbortSignal) =>
    request<AdvisorReportDetail>(`/reports/${id}`, undefined, signal),
  generateReport: (body: Record<string, unknown> = {}) =>
    request<AdvisorReportDetail>("/reports/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  imports: (params: Record<string, QueryValue>, signal?: AbortSignal) =>
    request<PaginatedImports>(`/imports${queryString(params)}`, undefined, signal),
  importDetail: (id: number, signal?: AbortSignal) =>
    request<ImportDetail>(`/imports/${id}`, undefined, signal),
  importIssues: (id: number, signal?: AbortSignal) =>
    request<PaginatedIssues>(`/imports/${id}/errors?limit=50`, undefined, signal),
  upload: (kind: "billing" | "utilization", file: File, force = false) => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportResult>(`/imports/${kind}${force ? "?force=true" : ""}`, {
      method: "POST",
      body: form,
    });
  },
};

export function exportUrl(path: string, params: Record<string, QueryValue> = {}): string {
  return `${API_BASE}${path}${queryString(params)}`;
}
