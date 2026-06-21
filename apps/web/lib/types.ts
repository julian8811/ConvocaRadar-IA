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
