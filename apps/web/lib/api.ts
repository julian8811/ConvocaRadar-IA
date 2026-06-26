import type {
  AdminMetrics,
  Alert,
  AuditLog,
  DashboardSummary,
  Opportunity,
  OpportunityDocument,
  OpportunityList,
  OpportunityScore,
  OpportunitySemanticList,
  Report,
  Source,
  SourceHealth,
  SourceRunOverview,
  SourceRun,
  Task,
} from "@/lib/types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? getDefaultApiUrl();

function getDefaultApiUrl() {
  if (typeof window !== "undefined") {
    const isLocalhost = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    if (isLocalhost) {
      return "http://127.0.0.1:8000/api/v1";
    }
  }
  return "https://api.convocaradar.com/api/v1";
}

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("convocaradar_token");
}

export function setToken(token: string) {
  window.localStorage.setItem("convocaradar_token", token);
}

export function clearToken() {
  window.localStorage.removeItem("convocaradar_token");
}

function handleUnauthorized(path: string) {
  if (typeof window === "undefined" || path.startsWith("/auth/")) return;
  clearToken();
  if (window.location.pathname !== "/login") {
    window.location.replace("/login");
  }
}

function isAuthPath(path: string) {
  return path.startsWith("/auth/");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  if (!token && !isAuthPath(path)) {
    handleUnauthorized(path);
    throw new Error("Sesión requerida. Redirigiendo al inicio de sesión.");
  }
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    if (response.status === 401) {
      handleUnauthorized(path);
      throw new Error("Sesión expirada. Redirigiendo al inicio de sesión.");
    }
    throw new Error(body.detail ?? "Request failed");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function filenameFromDisposition(disposition: string | null, fallback: string) {
  if (!disposition) return fallback;
  const match = disposition.match(/filename="([^";]+)"/i);
  return match?.[1] ?? fallback;
}

export async function downloadReport(report: Report) {
  const token = getToken();
  const response = await fetch(`${API_URL}/reports/${report.id}/download`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
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
  const token = getToken();
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_URL}/opportunities/${opportunityId}/documents`, {
    method: "POST",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: form,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? "Upload failed");
  }
  return response.json() as Promise<OpportunityDocument>;
}

export async function downloadOpportunityDocument(doc: OpportunityDocument) {
  const token = getToken();
  const response = await fetch(`${API_URL}/opportunity-documents/${doc.id}/download`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
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
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  register: (payload: Record<string, unknown>) =>
    request<{ access_token: string }>("/auth/register", { method: "POST", body: JSON.stringify(payload) }),
  me: () => request<{ name: string; email: string; role: string }>("/me"),
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
  tasks: () => request<Task[]>("/tasks"),
};
