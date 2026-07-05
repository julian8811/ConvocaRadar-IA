import type {
  AdminMetrics,
  Alert,
  AuditLog,
  DashboardSummary,
  HealthRead,
  Opportunity,
  OpportunityDocument,
  OpportunityList,
  OpportunityScore,
  OpportunitySemanticList,
  PipelineRead,
  Report,
  Source,
  SourceHealth,
  SourceRunOverview,
  SourceRun,
  Task,
  TriageRead,
} from "@/lib/types";

export const API_URL =
  // Use || (not ??) so an empty-string env var triggers the fallback too.
  // Vercel allows setting an env var to "" without deleting it, and we don't
  // want a broken "" base URL to ship to production.
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || getDefaultApiUrl();

/** SEC-1.5: cookie name. Must match the backend's TOKEN_COOKIE_NAME. */
export const TOKEN_COOKIE_NAME = "convocaradar_token";

/** SEC-1.5: legacy localStorage key used by pre-cookie clients. */
const LEGACY_TOKEN_STORAGE_KEY = "convocaradar_token";

/** SEC-1.5: request timeout — 12s per the spec. */
const REQUEST_TIMEOUT_MS = 12_000;

/**
 * Is the running environment "production"?
 *
 * SEC-1.5: the legacy localStorage Bearer fallback is ONLY allowed in
 * non-production. In production we never read localStorage — the cookie is
 * the sole auth path.
 */
function isProduction(): boolean {
  return process.env.NEXT_PUBLIC_ENV === "production";
}

function getDefaultApiUrl() {
  if (typeof window !== "undefined") {
    const isLocalhost = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    if (isLocalhost) {
      return "http://127.0.0.1:8000/api/v1";
    }
  }
  return "https://api.convocaradar.com/api/v1";
}

/**
 * Read a legacy token from localStorage.
 *
 * SEC-1.5: in production this MUST return null — no localStorage reads.
 * In development it returns the stored token so pre-cookie clients can
 * keep using `Authorization: Bearer`.
 */
function readLegacyToken(): string | null {
  if (isProduction()) return null;
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(LEGACY_TOKEN_STORAGE_KEY);
}

/**
 * Legacy `getToken` helper kept for backward compatibility with code that
 * imported it. Reads from localStorage in dev, returns null in production.
 */
export function getToken(): string | null {
  return readLegacyToken();
}

/**
 * Legacy `setToken` — kept so existing imports don't break. The cookie is
 * the real auth path now; this just mirrors the value to localStorage in
 * non-production for the legacy Bearer fallback to keep working.
 */
export function setToken(token: string): void {
  if (isProduction()) return;
  if (typeof window === "undefined") return;
  window.localStorage.setItem(LEGACY_TOKEN_STORAGE_KEY, token);
}

/**
 * Legacy `clearToken` — kept so existing imports don't break. Clears the
 * localStorage mirror in non-production.
 */
export function clearToken(): void {
  if (isProduction()) return;
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(LEGACY_TOKEN_STORAGE_KEY);
}

function handleUnauthorized(path: string) {
  if (typeof window === "undefined" || path.startsWith("/auth/")) return;
  clearToken();
  if (window.location.pathname !== "/login") {
    window.location.replace("/login");
  }
}

/**
 * SEC-1.5: wrap fetch with an AbortController that fires after 12s.
 * Exposed for testing — production code uses the `api` object below.
 */
/** Retry delay when the Render free-tier server is waking up (sleep -> wake takes ~30s). */
const RETRY_DELAYS_MS = [3_000, 8_000, 15_000, 25_000, 40_000];

export async function request<T>(path: string, init: RequestInit = {}, timeoutMs: number = REQUEST_TIMEOUT_MS): Promise<T> {
  const lastError: Error[] = [];

  for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt++) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);

    // Legacy Bearer fallback: only in non-production, only if a token is in
    // localStorage. In production this is always null.
    const legacyToken = readLegacyToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(init.headers as Record<string, string> | undefined),
    };
    if (legacyToken) {
      headers["Authorization"] = `Bearer ${legacyToken}`;
    }

    try {
      const response = await fetch(`${API_URL}${path}`, {
        ...init,
        signal: controller.signal,
        credentials: "include",
        headers,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: response.statusText }));
        if (response.status === 401) {
          if (path.startsWith("/auth/")) {
            throw new Error(body.detail ?? "Credenciales inválidas");
          }
          handleUnauthorized(path);
          throw new Error("Sesión expirada. Redirigiendo al inicio de sesión.");
        }
        throw new Error(body.detail ?? "Request failed");
      }
      if (response.status === 204) return undefined as T;
      return response.json() as Promise<T>;
    } catch (err) {
      const isServerWaking =
        err instanceof TypeError && (err.message === "Failed to fetch" || err.message.includes("TypeError"))
        || err instanceof DOMException && err.name === "AbortError";
      if (!isServerWaking || attempt >= RETRY_DELAYS_MS.length) {
        throw err;
      }
      lastError.push(err as Error);
      // Server is waking up (Render free tier), wait and retry
      await new Promise((r) => setTimeout(r, RETRY_DELAYS_MS[attempt]));
    } finally {
      clearTimeout(timeout);
    }
  }

  throw lastError[lastError.length - 1] ?? new Error("Request failed after retries");
}

function filenameFromDisposition(disposition: string | null, fallback: string) {
  if (!disposition) return fallback;
  const match = disposition.match(/filename="([^";]+)"/i);
  return match?.[1] ?? fallback;
}

export async function downloadReport(report: Report) {
  const legacyToken = readLegacyToken();
  const headers: Record<string, string> = {};
  if (legacyToken) {
    headers["Authorization"] = `Bearer ${legacyToken}`;
  }
  const response = await fetch(`${API_URL}/reports/${report.id}/download`, {
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? "Download failed");
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filenameFromDisposition(response.headers.get("content-disposition"), `convocaradar-${report.id}.${report.format}`);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

export async function uploadOpportunityDocument(opportunityId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_URL}/opportunities/${opportunityId}/documents`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? "Upload failed");
  }
  return response.json() as Promise<OpportunityDocument>;
}

export async function downloadOpportunityDocument(doc: OpportunityDocument) {
  const response = await fetch(`${API_URL}/opportunity-documents/${doc.id}/download`, {
    credentials: "include",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? "Download failed");
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = doc.file_name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

export const api = {
  login: (email: string, password: string) =>
    // SEC-RENDER-STARTUP: Render free tier cold-starts in 30-60s. Use 65s
    // timeout so the first request after idle doesn't get aborted before
    // the server wakes up. The retry mechanism in request() handles
    // additional connection errors during wake-up.
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }, 65_000),
  register: (payload: Record<string, unknown>) =>
    // Same cold-start concern as login.
    request<{ access_token: string }>("/auth/register", { method: "POST", body: JSON.stringify(payload) }, 65_000),
  logout: () => request<{ detail: string }>("/auth/logout", { method: "POST" }),
  me: () => request<{ name: string; email: string; role: string }>("/me"),
  // PR B-2 (dashboard-redesign): the new 3-zone endpoints. Each zone
  // (Triage / Pipeline / Health) calls its own endpoint independently
  // so a slow endpoint cannot block the others. dashboardSummary
  // remains as a thin merged alias for the e2e and any external
  // clients that still depend on the legacy shape.
  dashboardTriage: () => request<TriageRead>("/dashboard/triage"),
  dashboardPipeline: () => request<PipelineRead>("/dashboard/pipeline"),
  // Health endpoint can be slow during background sweeps (123 sources).
  // Use a 45s timeout instead of the default 12s.
  dashboardHealth: () => request<HealthRead>("/dashboard/health", {}, 45_000),
  dashboardSummary: () => request<DashboardSummary>("/dashboard/summary"),
  organization: () => request<{ name: string; country: string; type: string }>("/organizations/current"),
  profile: () => request<Record<string, unknown>>("/organizations/current/profile"),
  updateProfile: (payload: Record<string, unknown>) =>
    request<Record<string, unknown>>("/organizations/current/profile", { method: "PUT", body: JSON.stringify(payload) }),
  opportunities: (query = "") => {
    const normalized = query && !query.startsWith("?") ? `?${query}` : query;
    return request<OpportunityList>(`/opportunities${normalized}`);
  },
  semanticSearch: (query: string, limit = 12) =>
    request<OpportunitySemanticList>(
      `/opportunities/semantic-search?query=${encodeURIComponent(query)}&limit=${limit}`,
    ),
  opportunity: (id: string) => request<Opportunity>(`/opportunities/${id}`),
  favorite: (id: string) => request(`/opportunities/${id}/favorite`, { method: "POST" }),
  unfavorite: (id: string) => request(`/opportunities/${id}/favorite`, { method: "DELETE" }),
  setOpportunityStatus: (id: string, status: string) =>
    request(`/opportunities/${id}/status?status=${encodeURIComponent(status)}`, { method: "POST" }),
  scores: (id: string) => request<OpportunityScore[]>(`/opportunities/${id}/scores`),
  score: (id: string) => request<OpportunityScore>(`/opportunities/${id}/scores`, { method: "POST" }),
  opportunityDocuments: (id: string) => request<OpportunityDocument[]>(`/opportunities/${id}/documents`),
  deleteOpportunityDocument: (id: string) => request(`/opportunity-documents/${id}`, { method: "DELETE" }),
  sources: () => request<Source[]>("/sources"),
  sourceHealth: () => request<SourceHealth[]>("/sources/health"),
  createSource: (payload: Record<string, unknown>) =>
    request<Source>("/sources", { method: "POST", body: JSON.stringify(payload) }),
  runSource: (id: string) => request<SourceRun>(`/sources/${id}/run`, { method: "POST" }),
  runAllSources: () => request<SourceRun[]>("/sources/run-all", { method: "POST" }),
  sourceRuns: (id: string) => request<SourceRun[]>(`/sources/${id}/runs`),
  reports: () => request<Report[]>("/reports"),
  createReport: (payload: Record<string, unknown>) =>
    request<Report>("/reports", { method: "POST", body: JSON.stringify(payload) }),
  regenerateReport: (id: string) => request<Report>(`/reports/${id}/regenerate`, { method: "POST" }),
  deleteReport: (id: string) => request(`/reports/${id}`, { method: "DELETE" }),
  alerts: () => request<Alert[]>("/alerts"),
  createAlert: (payload: Record<string, unknown>) =>
    request<Alert>("/alerts", { method: "POST", body: JSON.stringify(payload) }),
  generateAlerts: () => request<Alert[]>("/alerts/generate", { method: "POST" }),
  updateAlert: (id: string, payload: Record<string, unknown>) =>
    request<Alert>(`/alerts/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  sendAlert: (id: string) => request<Alert>(`/alerts/${id}/send`, { method: "POST" }),
  deleteAlert: (id: string) => request(`/alerts/${id}`, { method: "DELETE" }),
  testAlert: (recipient: string) =>
    request<Alert>("/alerts/test", { method: "POST", body: JSON.stringify({ recipient }) }),
  auditLogs: () => request<AuditLog[]>("/admin/audit-logs"),
  sourceRunsOverview: () => request<SourceRunOverview[]>("/admin/source-runs"),
  adminMetrics: () => request<AdminMetrics>("/admin/metrics"),
  retryDegradedSources: () =>
    request<{ sources_checked: number; scheduled: number; skipped: number }>("/admin/sources/retry-degraded", { method: "POST" }),
  bootstrapData: () => request<Record<string, string | number>>("/admin/bootstrap-data", { method: "POST" }),
  summarizeAllOpportunities: (limit = 10) =>
    request<{ processed: number; summarized: number }>(
      `/admin/opportunities/summarize-all?limit=${limit}`,
      { method: "POST" },
    ),
  scoreAllOpportunities: (limit = 10) =>
    request<{ processed: number; scored: number }>(
      `/admin/opportunities/score-all?limit=${limit}`,
      { method: "POST" },
    ),
  sendWeeklyDigest: () =>
    request<{ delivered: boolean; opportunities: number }>("/admin/alerts/send-digest", { method: "POST" }),
  tasks: () => request<Task[]>("/tasks"),
};
