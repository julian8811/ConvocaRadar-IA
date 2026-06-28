export type Opportunity = {
  id: string;
  source_id: string | null;
  title: string;
  entity: string;
  country: string;
  region: string | null;
  categories: string[];
  topics: string[];
  description: string;
  summary: string;
  status: "open" | "closed" | "closing_soon" | "unknown" | string;
  close_date: string | null;
  open_date: string | null;
  funding_amount_value: number | null;
  funding_amount_currency: string | null;
  funding_amount_raw: string | null;
  official_url: string | null;
  application_url: string | null;
  language: string;
  requirements: string[];
  documents_required: string[];
  risk_flags: string[];
  user_status: string;
  is_favorite: boolean;
};

export type OpportunityDocument = {
  id: string;
  opportunity_id: string;
  file_name: string;
  file_type: string;
  file_url: string | null;
  storage_path: string | null;
  checksum: string | null;
  created_at: string;
};

export type OpportunityList = {
  items: Opportunity[];
  total: number;
  page: number;
  page_size: number;
};

export type OpportunitySemanticMatch = {
  opportunity: Opportunity;
  similarity: number;
};

export type OpportunitySemanticList = {
  query: string;
  items: OpportunitySemanticMatch[];
};

export type OpportunityScore = {
  id: string;
  opportunity_id: string;
  organization_id: string;
  score: number;
  priority: "high" | "medium" | "low" | "not_recommended" | string;
  reasons: string[];
  warnings: string[];
  calculated_at: string;
};

export type Source = {
  id: string;
  name: string;
  key: string;
  base_url: string;
  country: string;
  region: string;
  source_type: string;
  category: string[];
  enabled: boolean;
  scraping_frequency: string;
  last_run_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
};

export type SourceHealth = {
  source_id: string;
  key: string;
  name: string;
  source_type: string;
  status: "healthy" | "degraded" | "failing" | "idle" | string;
  last_run_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  recent_runs: number;
  recent_failures: number;
  recent_items_found: number;
  recent_items_created: number;
  recent_items_updated: number;
  last_run_status: string | null;
  success_rate: number;
  failure_rate: number;
  average_items_found: number;
  last_run_duration_seconds: number | null;
  days_since_last_success: number | null;
};

export type SourceRun = {
  id: string;
  source_id: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  items_found: number;
  items_created: number;
  items_updated: number;
  items_failed: number;
  error_message: string | null;
  logs: Array<Record<string, unknown>>;
};

export type Report = {
  id: string;
  title: string;
  report_type: string;
  format: string;
  status: string;
  html_content: string;
  generated_at: string;
};

export type ReportFormat = "html" | "pdf" | "xlsx" | "csv";

export type Alert = {
  id: string;
  alert_type: string;
  channel: string;
  recipient: string;
  subject: string;
  message: string;
  status: string;
  scheduled_at: string | null;
  sent_at: string | null;
  created_at: string;
};

export type AuditLog = {
  id: string;
  organization_id: string | null;
  user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  created_at: string;
};

export type Task = {
  id: string;
  organization_id: string | null;
  source_run_id: string | null;
  task_type: string;
  provider: string;
  status: string;
  external_id: string | null;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};

export type SourceRunOverview = Task & {
  source_key: string;
  source_name: string;
  items_found: number;
  items_created: number;
  items_updated: number;
  items_failed: number;
  error_message: string | null;
  logs: Array<Record<string, unknown>>;
};

export type AdminMetrics = {
  active_sources: number;
  total_sources: number;
  degraded_sources: number;
  failing_sources: number;
  stale_sources: number;
  opportunities: number;
  open_opportunities: number;
  closing_soon_opportunities: number;
  embeddings_total: number;
  embeddings_missing: number;
  embeddings_coverage: number;
  failed_source_runs: number;
  failed_tasks: number;
  reports: number;
  pending_alerts: number;
  source_health_alerts: number;
  sent_alerts: number;
  audit_events: number;
};

export type DashboardBreakdownItem = {
  name: string;
  total: number;
};

export type DashboardOpportunityItem = {
  id: string;
  title: string;
  entity: string;
  country: string;
  status: string;
  close_date: string | null;
  funding_amount_raw: string | null;
  funding_amount_value: number | null;
  funding_amount_currency: string | null;
  score: number | null;
  priority: string | null;
  days_to_close: number | null;
};

export type DashboardSourceAlert = {
  source_id: string;
  name: string;
  status: "degraded" | "failing";
};

export type DashboardDataCoverage = {
  with_summary: number;
  with_amount: number;
  with_close_date: number;
  with_source: number;
  embeddings_coverage: number;
};

export type DashboardProfileSummary = {
  completeness: number;
  missing_fields: string[];
};

export type DashboardSummary = {
  total_opportunities: number;
  open_opportunities: number;
  closing_soon_opportunities: number;
  high_match_opportunities: number;
  top_scored: DashboardOpportunityItem[];
  closing_soon: DashboardOpportunityItem[];
  status_breakdown: DashboardBreakdownItem[];
  country_breakdown: DashboardBreakdownItem[];
  degraded_sources: number;
  failing_sources: number;
  source_alerts: DashboardSourceAlert[];
  data_coverage: DashboardDataCoverage;
  profile: DashboardProfileSummary;
};

/**
 * PR B-2 (dashboard-redesign): Triage zone payload.
 * Slim opportunity item used by /dashboard/triage (review queue + 7-day
 * closing window). The backend's TriageOpportunityItem excludes entity,
 * status, and close_date (which are too wide for the hero lane) and
 * adds source_key for traceability.
 */
export type TriageOpportunityItem = {
  id: string;
  title: string;
  country: string | null;
  currency: string | null;
  funding_amount: number | null;
  days_to_close: number | null;
  score: number | null;
  source_key: string | null;
};

export type TriageRead = {
  review_queue: TriageOpportunityItem[];
  closing_soon_7d: TriageOpportunityItem[];
};

/**
 * PR B-2 (dashboard-redesign): Pipeline zone payload.
 * Slim opportunity item used by /dashboard/pipeline (top_scored with
 * reasons + closing_soon countdown). Mirrors the backend's
 * PipelineOpportunityItem shape exactly.
 */
export type PipelineOpportunityItem = {
  id: string;
  title: string;
  country: string | null;
  currency: string | null;
  funding_amount: number | null;
  days_to_close: number | null;
  score: number | null;
  reasons: string[];
  source_key: string | null;
};

export type PipelineRead = {
  top_scored: PipelineOpportunityItem[];
  closing_soon: PipelineOpportunityItem[];
};

/**
 * PR B-2 (dashboard-redesign): Health zone payload.
 * Mirrors the backend's HealthRead shape. `data_coverage.embeddings_coverage`
 * is nullable (null when no opportunities exist; the frontend renders
 * "Sin datos aún" in that case).
 */
export type HealthKpis = {
  total: number;
  open: number;
  closing_soon: number;
  high_match: number;
};

export type HealthRead = {
  kpis: HealthKpis;
  status_breakdown: DashboardBreakdownItem[];
  country_breakdown: DashboardBreakdownItem[];
  data_coverage: DashboardDataCoverage;
  sources_health: SourceHealth[];
  failing_sources: number;
  degraded_sources: number;
  source_alerts: DashboardSourceAlert[];
  // Analytics charts (PR analytics-dashboard)
  score_distribution: DashboardBreakdownItem[];
  funding_ranges: DashboardBreakdownItem[];
  source_contribution: DashboardBreakdownItem[];
  opportunities_timeline: DashboardBreakdownItem[];
  category_distribution: DashboardBreakdownItem[];
};

/**
 * PR B-2: Top-level KPI shape for the 4 cards demoted into the
 * <details> footer in the Triage zone (re-used by HealthZone
 * for the same 4-card strip). Kept separate from HealthKpis
 * (which uses short keys) for backward-compat with the legacy
 * DashboardSummary shape that the e2e + alias still emit.
 */
export type DashboardKpiCard = {
  total_opportunities: number;
  open_opportunities: number;
  closing_soon_opportunities: number;
  high_match_opportunities: number;
};

/**
 * PR B-2: "Mi cola de revisión" — items the consultor has marked as
 * review/kept. Reuses TriageOpportunityItem (same slim shape, sourced
 * from the user's review_queue slice on /dashboard/triage).
 */
export type ReviewQueueItem = TriageOpportunityItem;
