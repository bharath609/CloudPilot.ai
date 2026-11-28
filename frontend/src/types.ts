export type Currency = "USD" | "EUR" | "INR";

export const CURRENCIES: Currency[] = ["USD", "EUR", "INR"];

export interface Freshness {
  data_age_hours: number | null;
  freshness_warning: boolean;
  data_quality: string;
  note: string;
}

export interface Filters {
  currencies: string[];
  providers: string[];
  services: string[];
  projects: string[];
  regions: string[];
  environments: string[];
  billing: { start: string | null; end: string | null; row_count: number; days: number };
  last_import_at: string | null;
  freshness: Freshness;
  synthetic_data: boolean;
  data_source: "demo" | "imported" | "mixed" | "empty";
  note: string;
}

export interface Summary {
  currency: string;
  total_spend: string;
  row_count: number;
  window: { start: string | null; end: string | null; days: number };
  recent_vs_prior_pct: number | null;
  top_services: { service: string; amount: string; pct: number }[];
}

export interface CostPoint {
  period: string;
  amount: string;
  currency: string;
}

export interface Costs {
  currency: string;
  granularity: string;
  series: CostPoint[];
}

export interface Resource {
  resource_id: string;
  name: string;
  resource_type: string;
  provider: string;
  environment: string;
  region: string;
  currency: string;
  cost_per_hour: string;
  cpu_pct: number;
  memory_pct: number;
  status: string;
}

export interface Decision {
  decision: string;
  note: string | null;
  reviewer: string;
  created_at: string;
}

export interface Finding {
  id: string;
  resource_id: string;
  finding_type: string;
  currency: string;
  baseline_monthly_cost: string;
  current_sku: string;
  recommended_sku: string;
  evidence: string[];
  assumptions: string[];
  warnings: string[];
  confidence: string;
  risk: string;
  latest_decision: Decision | null;
}

export interface ForecastPoint {
  date: string;
  amount: string;
  low?: string;
  high?: string;
  currency?: string;
}

export interface Forecast {
  currency: string;
  history: { date: string; amount: string }[];
  forecast: ForecastPoint[];
  metrics: { mae: number; rmse: number; mape: number } | null;
}

export interface ImportRow {
  id: number;
  filename: string;
  source: string;
  currency: string;
  row_count: number;
  imported_at: string;
  dataset?: string;
}

export interface DataStatusCurrency {
  currency: string;
  rows: number;
  start: string | null;
  end: string | null;
  total: string;
  resources: number;
  findings: number;
  origin: "demo" | "uploaded" | "mixed";
}

export interface DataStatus {
  mode: "demo" | "imported" | "mixed" | "empty";
  currencies: DataStatusCurrency[];
  total_rows: number;
  allowed_currencies: string[];
  last_import_at: string | null;
}

export interface ImportIssue {
  line: number;
  message: string;
}

export interface ImportReport {
  ok: boolean;
  dataset: string;
  filename: string;
  mode: string;
  accepted: number;
  rejected: number;
  currencies: Record<string, number>;
  errors: ImportIssue[];
  warnings: string[];
  message: string;
  findings_generated?: number;
}

export interface AssistantFact {
  label: string;
  value: string;
}

export interface AssistantAnswer {
  answer: string;
  intent: string;
  currency: string;
  facts: AssistantFact[];
  sources: string[];
  confidence: "high" | "medium" | "low";
  grounded: boolean;
  mode: string;
  suggestions: string[];
}

export interface AuditRow {
  id: number;
  finding_id: string;
  decision: string;
  note: string | null;
  reviewer: string;
  created_at: string;
  resource_id: string | null;
  finding_type: string | null;
  currency: string | null;
}

export interface SimulationResult {
  resource_id: string;
  scenario: string;
  currency: string;
  baseline_monthly_cost: string;
  projected_monthly_cost: string;
  projected_monthly_savings: string;
  confidence: string;
  assumptions: string[];
  warnings: string[];
  production_isolated: boolean;
  note: string;
}

export interface AnomalyResult {
  kind: string;
  currency: string;
  detected: boolean;
  description: string;
  confidence: string;
  baseline: number;
  current: number;
  change_pct: number;
  threshold: number;
  evidence: string[];
  data_gaps: string[];
  recommended_actions: string[];
}

export interface PolicyResult {
  allowed: boolean;
  action_type: string;
  resource_id: string;
  environment: string;
  requires_approval: boolean;
  rule_id: string | null;
  violations: string[];
}

export interface Investigation {
  investigation_id: string;
  finding_id: string;
  currency: string;
  status: string;
  steps: { step: number; name: string; finding: string }[];
  causes: { cause: string; likelihood: string; supporting_evidence: string[] }[];
  data_gaps: string[];
  recommended_actions: string[];
  confidence: number;
}
