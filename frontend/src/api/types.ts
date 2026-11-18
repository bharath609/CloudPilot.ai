/**
 * Typed mirrors of the CloudPilot AI API contracts.
 *
 * Money and percentage fields are exact decimal *strings* on purpose: the
 * backend never sends binary floats, and the UI must not introduce them.
 */

export type Money = string;
export type Percent = string;

export interface CurrencyTotal {
  currency: string;
  amount: Money;
  row_count: number;
}

export interface CostWindow {
  start: string | null;
  end: string | null;
  days: number | null;
}

export interface CostSummary {
  window: CostWindow;
  totals: CurrencyTotal[];
  row_count: number;
  excluded_duplicate_rows: number;
  import_ids: number[];
  import_count: number;
  contains_sample_data: boolean;
  notes: string[];
}

export interface BreakdownItem {
  key: string;
  currency: string;
  amount: Money;
  row_count: number;
  share_pct: Percent;
}

export interface CostBreakdown {
  dimension: string;
  window: CostWindow;
  currency: string | null;
  totals: CurrencyTotal[];
  items: BreakdownItem[];
  total_groups: number;
  items_truncated: boolean;
  excluded_duplicate_rows: number;
  notes: string[];
}

export interface TrendPoint {
  bucket: string;
  currency: string;
  amount: Money;
  row_count: number;
}

export interface CostTrends {
  granularity: "day" | "month";
  window: CostWindow;
  currency: string | null;
  points: TrendPoint[];
  totals: CurrencyTotal[];
  excluded_duplicate_rows: number;
  notes: string[];
}

export interface FilterOptions {
  window_start: string | null;
  window_end: string | null;
  day_count: number | null;
  currencies: string[];
  providers: string[];
  services: string[];
  regions: string[];
  environments: string[];
  projects: string[];
  accounts: string[];
  import_count: number;
  last_import_at: string | null;
  last_import_filename: string | null;
  last_billing_date: string | null;
  contains_sample_data: boolean;
  synthetic_price_count: number;
  notes: string[];
}

export interface Health {
  status: "ok" | "degraded";
  app: string;
  version: string;
  environment: string;
  database: "ok" | "error";
  time: string;
}

export type FindingType = "idle_resource" | "over_provisioned";
export type RiskLevel = "low" | "medium" | "high";
export type ConfidenceLevel = "low" | "medium" | "high";
export type DecisionKind = "approve" | "reject" | "needs_owner_review";

export interface PriceSource {
  source_name?: string;
  source_url?: string;
  is_synthetic?: boolean;
  [key: string]: unknown;
}

export interface Decision {
  id: number;
  finding_id: number;
  decision: DecisionKind;
  actor: string;
  note: string | null;
  created_at: string;
}

export interface DecisionListItem extends Decision {
  finding_type: FindingType;
  resource_id: string;
  service: string;
  environment: string;
  project: string;
  currency: string;
  risk: RiskLevel;
  estimated_monthly_savings: Money;
  cost_window_start: string;
  cost_window_end: string;
}

export interface DecisionListResponse {
  items: DecisionListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface SavingsScenario {
  id: number;
  method: "stop_resource" | "rightsize_sku";
  currency: string;
  baseline_monthly_cost: Money;
  proposed_monthly_cost: Money;
  estimated_monthly_savings: Money;
  assumptions: string[];
}

export interface Finding {
  id: number;
  run_id: number;
  finding_type: FindingType;
  status: string;
  provider: string;
  account_id: string;
  service: string;
  resource_id: string;
  region: string;
  environment: string;
  project: string;
  currency: string;
  current_sku: string | null;
  recommended_sku: string | null;
  baseline_monthly_cost: Money;
  proposed_monthly_cost: Money;
  estimated_monthly_savings: Money;
  savings_pct: Percent;
  confidence: ConfidenceLevel;
  risk: RiskLevel;
  cost_window_start: string;
  cost_window_end: string;
  observation_start: string | null;
  observation_end: string | null;
  observation_days: number;
  sample_count: number;
  metrics: Record<string, string | number | null>;
  evidence: Record<string, unknown>;
  assumptions: string[];
  warnings: string[];
  price_source: PriceSource;
  uses_synthetic_prices: boolean;
  created_at: string;
  scenario: SavingsScenario | null;
  decision: Decision | null;
}

export interface AnalysisRunSummary {
  id: number;
  status: string;
  reference_date: string | null;
  cost_window_start: string | null;
  cost_window_end: string | null;
  currency: string | null;
  filters: Record<string, string>;
  rule_config: Record<string, unknown>;
  finding_count: number;
  total_savings_by_currency: Record<string, Money>;
  uses_synthetic_prices: boolean;
  notes: string[];
  stats: Record<string, unknown>;
  duration_ms: number;
  created_at: string;
}

export interface FindingListResponse {
  run: AnalysisRunSummary | null;
  items: Finding[];
  total: number;
  limit: number;
  offset: number;
}

export interface ResourceHealthItem {
  resource_id: string;
  provider: string;
  service: string;
  region: string;
  environment: string;
  project: string;
  owner: string | null;
  team: string | null;
  currency: string | null;
  window_cost: Money | null;
  observation_start: string | null;
  observation_end: string | null;
  observation_days: number;
  sample_count: number;
  cpu_avg_pct: Percent;
  cpu_p95_max_pct: Percent;
  memory_avg_pct: Percent;
  memory_p95_max_pct: Percent;
  network_in_bytes: number;
  network_out_bytes: number;
  idle_candidate: boolean;
  rightsize_candidate: boolean;
  warnings: string[];
}

export interface ResourceHealthResponse {
  window: { start: string; end: string; days: number };
  items: ResourceHealthItem[];
  total: number;
  limit: number;
  offset: number;
  thresholds: Record<string, string>;
  contains_sample_data: boolean;
  notes: string[];
}

export interface ForecastPoint {
  period: string;
  predicted_cost: Money;
  lower_bound: Money;
  upper_bound: Money;
}

export interface ForecastEvaluation {
  method: "seasonal_naive" | "moving_average";
  history_days: number;
  train_days: number;
  holdout_days: number;
  evaluated_points: number;
  mae: Money;
  rmse: Money;
  bias: Money;
  mape_pct: Percent | null;
  mape_excluded_points: number;
  interval_quantile: Percent;
  interval_width: Money;
  confidence: ConfidenceLevel;
  warnings: string[];
}

export interface ForecastSeries {
  currency: string;
  history_start: string;
  history_end: string;
  horizon_start: string;
  horizon_end: string;
  history_days: number;
  points: ForecastPoint[];
  evaluation: ForecastEvaluation;
  projected_total: Money;
  projected_lower: Money;
  projected_upper: Money;
  notes: string[];
}

export interface ForecastRunSummary {
  id: number;
  status: string;
  method: "seasonal_naive" | "moving_average";
  granularity: "day";
  reference_date: string | null;
  history_start: string | null;
  history_end: string | null;
  horizon_start: string | null;
  horizon_end: string | null;
  currency: string | null;
  filters: Record<string, string>;
  config: Record<string, unknown>;
  series_count: number;
  evaluation: Record<string, unknown>;
  stats: Record<string, unknown>;
  notes: string[];
  warnings: string[];
  duration_ms: number;
  created_at: string;
}

export interface ForecastResult {
  run: ForecastRunSummary;
  series: ForecastSeries[];
}

export interface ForecastListResponse {
  run: ForecastRunSummary | null;
  series: ForecastSeries[];
  total: number;
}

export interface AdvisorFinding {
  finding_id: string;
  explanation: string;
  evidence_ids: string[];
  assumptions: string[];
  risk: RiskLevel;
  recommended_next_step: string;
}

export interface AdvisorOutput {
  executive_summary: string;
  priority_findings: AdvisorFinding[];
  unknowns: string[];
  human_review_required: true;
}

export interface AdvisorReportSummary {
  id: number;
  status: string;
  mode: "llm" | "deterministic";
  ai_used: boolean;
  provider: string | null;
  model: string | null;
  analysis_run_id: number | null;
  forecast_run_id: number | null;
  fallback_reason: string | null;
  validation_errors: string[];
  evidence_sha256: string;
  attempts: number;
  latency_ms: number;
  duration_ms: number;
  created_at: string;
  completed_at: string | null;
}

export interface AdvisorReportDetail extends AdvisorReportSummary {
  output: AdvisorOutput;
  evidence: Record<string, unknown>;
  notes: string[];
  warnings: string[];
}

export interface AdvisorReportListResponse {
  items: AdvisorReportSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ValidationIssue {
  row_number: number;
  column: string | null;
  code: string;
  severity: "error" | "warning";
  message: string;
  raw_value: string | null;
}

export interface ImportSummary {
  id: number;
  kind: "billing" | "utilization";
  filename: string;
  status: string;
  provider: string | null;
  row_count: number;
  accepted_row_count: number;
  rejected_row_count: number;
  warning_count: number;
  currencies: string[];
  period_start: string | null;
  period_end: string | null;
  source: string;
  content_sha256: string;
  created_at: string;
}

export interface ImportResult extends ImportSummary {
  stats: Record<string, unknown>;
  issues: ValidationIssue[];
  issues_truncated: boolean;
  message: string;
}

export interface ImportDetail extends ImportSummary {
  content_bytes: number;
  stats: Record<string, unknown>;
  issue_count: number;
  error_count: number;
}

export interface PaginatedImports {
  items: ImportSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface PaginatedIssues {
  items: ValidationIssue[];
  total: number;
  limit: number;
  offset: number;
}
