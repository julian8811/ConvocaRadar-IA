/**
 * SEC-1.5 frontend: JWT cookie + Bearer dual-support + fetch timeout.
 *
 * Covers the request() helper exposed by apps/web/lib/api.ts:
 *   - 12s AbortController timeout (not 30s).
 *   - localStorage Bearer fallback for legacy clients, gated on
 *     NEXT_PUBLIC_ENV !== "production".
 *   - credentials: "include" so the cookie is sent.
 *   - AbortError surfaces as a distinct error from network errors.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  cleanupRequestModule();
  vi.unstubAllEnvs();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/**
 * Dynamic import helper. Returns the module AFTER vi.stubEnv has been
 * applied, so the env-var reads inside the module see the stubbed values.
 */
async function loadApiModule() {
  vi.resetModules();
  const mod = await import("@/lib/api");
  return mod;
}

function cleanupRequestModule() {
  // Reset the module cache so each test re-evaluates with fresh env stubs.
  vi.resetModules();
}

interface FetchCapture {
  signal: AbortSignal | null;
  init: RequestInit | null;
}

describe("SEC-1.5 — request() timeout (AbortController)", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "development");
  });

  it("aborts the request after 12 seconds and surfaces AbortError", async () => {
    let externalReject: (err: Error) => void = () => {};
    const externalPromise = new Promise<Response>((_resolve, reject) => {
      externalReject = reject;
    });
    externalPromise.catch(() => {});

    const capture: FetchCapture = { signal: null, init: null };
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit = {}) => {
        capture.signal = init.signal ?? null;
        capture.init = init;
        if (init.signal) {
          init.signal.addEventListener("abort", () => {
            const err = new Error("aborted");
            err.name = "AbortError";
            externalReject(err);
          });
        }
        return externalPromise;
      }),
    );

    const { request } = await loadApiModule();
    vi.useFakeTimers();

    const promise = request<unknown>("/me");
    promise.catch(() => {});

    await vi.advanceTimersByTimeAsync(12_000);

    await expect(promise).rejects.toMatchObject({ name: "AbortError" });
    expect(capture.signal).not.toBeNull();
  });

  it("uses a 12-second timeout, not 30 seconds", async () => {
    let externalReject: (err: Error) => void = () => {};
    const externalPromise = new Promise<Response>((_resolve, reject) => {
      externalReject = reject;
    });
    externalPromise.catch(() => {});

    const capture: FetchCapture = { signal: null, init: null };
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit = {}) => {
        capture.signal = init.signal ?? null;
        capture.init = init;
        if (init.signal) {
          init.signal.addEventListener("abort", () => {
            const err = new Error("aborted");
            err.name = "AbortError";
            externalReject(err);
          });
        }
        return externalPromise;
      }),
    );

    const { request } = await loadApiModule();
    vi.useFakeTimers();

    const promise = request<unknown>("/me");
    promise.catch(() => {});

    // At t=11_999ms, the AbortController should NOT have fired yet.
    await vi.advanceTimersByTimeAsync(11_999);
    expect(capture.signal?.aborted).toBe(false);

    // At t=12_000ms exactly, it must abort.
    await vi.advanceTimersByTimeAsync(1);
    expect(capture.signal?.aborted).toBe(true);
    await expect(promise).rejects.toMatchObject({ name: "AbortError" });
  });

  it("passes credentials: 'include' so the HttpOnly cookie is sent", async () => {
    const capture: FetchCapture = { signal: null, init: null };
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit = {}) => {
        capture.signal = init.signal ?? null;
        capture.init = init;
        return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
      }),
    );

    const { request } = await loadApiModule();
    const result = await request<{ ok: boolean }>("/me");
    expect(result.ok).toBe(true);
    expect(capture.init?.credentials).toBe("include");
  });
});

describe("SEC-1.5 — localStorage Bearer fallback (legacy clients)", () => {
  beforeEach(() => {
    if (typeof window !== "undefined") {
      window.localStorage.clear();
    }
  });

  it("in development, sends Authorization: Bearer header when a legacy localStorage token exists", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "development");
    window.localStorage.setItem("convocaradar_token", "legacy-dev-token");

    const capture: FetchCapture = { signal: null, init: null };
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit = {}) => {
        capture.init = init;
        return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
      }),
    );

    const { request } = await loadApiModule();
    await request<{ ok: boolean }>("/me");

    const headers = capture.init?.headers as Record<string, string> | undefined;
    expect(headers?.Authorization).toBe("Bearer legacy-dev-token");
  });

  it("in production, NEVER reads from localStorage (no Bearer header)", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "production");
    window.localStorage.setItem("convocaradar_token", "should-be-ignored");

    const capture: FetchCapture = { signal: null, init: null };
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit = {}) => {
        capture.init = init;
        return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
      }),
    );

    const { request } = await loadApiModule();
    await request<{ ok: boolean }>("/me");

    const headers = capture.init?.headers as Record<string, string> | undefined;
    // In production, the legacy localStorage fallback MUST NOT leak the token.
    expect(headers?.Authorization).toBeUndefined();
  });

  it("does not send Authorization header when no localStorage token exists (any env)", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "development");

    const capture: FetchCapture = { signal: null, init: null };
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit = {}) => {
        capture.init = init;
        return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
      }),
    );

    const { request } = await loadApiModule();
    await request<{ ok: boolean }>("/me");

    const headers = capture.init?.headers as Record<string, string> | undefined;
    expect(headers?.Authorization).toBeUndefined();
  });
});

describe("SEC-1.5 — request() error classification", () => {
  it("wraps a TypeError 'Failed to fetch' (network error) without naming it AbortError", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "development");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );

    const { request } = await loadApiModule();
    await expect(request<unknown>("/me")).rejects.toMatchObject({
      name: "TypeError",
    });
  });
});

/**
 * PR B-2 (dashboard-redesign): the 3 new zone methods on the API client
 * each hit their own endpoint. dashboardSummary stays as a backward-compat
 * alias for the e2e + external clients.
 */
describe("PR B-2 — dashboard zone methods", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "development");
  });

  it("api.dashboardTriage() issues a GET to /dashboard/triage", async () => {
    const capturedUrls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        capturedUrls.push(url);
        return Promise.resolve(new Response(JSON.stringify({ review_queue: [], closing_soon_7d: [] }), { status: 200 }));
      }),
    );

    const { api } = await loadApiModule();
    const result = await api.dashboardTriage();
    expect(capturedUrls).toHaveLength(1);
    expect(capturedUrls[0]).toMatch(/\/dashboard\/triage$/);
    expect(result.review_queue).toEqual([]);
    expect(result.closing_soon_7d).toEqual([]);
  });

  it("api.dashboardPipeline() issues a GET to /dashboard/pipeline", async () => {
    const capturedUrls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        capturedUrls.push(url);
        return Promise.resolve(new Response(JSON.stringify({ top_scored: [], closing_soon: [] }), { status: 200 }));
      }),
    );

    const { api } = await loadApiModule();
    const result = await api.dashboardPipeline();
    expect(capturedUrls).toHaveLength(1);
    expect(capturedUrls[0]).toMatch(/\/dashboard\/pipeline$/);
    expect(result.top_scored).toEqual([]);
    expect(result.closing_soon).toEqual([]);
  });

  it("api.dashboardHealth() issues a GET to /dashboard/health", async () => {
    const capturedUrls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        capturedUrls.push(url);
        return Promise.resolve(
          new Response(
            JSON.stringify({
              kpis: { total: 0, open: 0, closing_soon: 0, high_match: 0 },
              data_coverage: { with_summary: 0, with_amount: 0, with_close_date: 0, with_source: 0, embeddings_coverage: null },
              status_breakdown: [],
              country_breakdown: [],
              sources_health: [],
              failing_sources: 0,
              degraded_sources: 0,
              source_alerts: [],
            }),
            { status: 200 },
          ),
        );
      }),
    );

    const { api } = await loadApiModule();
    const result = await api.dashboardHealth();
    expect(capturedUrls).toHaveLength(1);
    expect(capturedUrls[0]).toMatch(/\/dashboard\/health$/);
    expect(result.data_coverage.embeddings_coverage).toBeNull();
  });

  it("api.dashboardSummary() still works against /dashboard/summary (backward compat)", async () => {
    const capturedUrls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        capturedUrls.push(url);
        return Promise.resolve(
          new Response(
            JSON.stringify({
              total_opportunities: 0,
              open_opportunities: 0,
              closing_soon_opportunities: 0,
              high_match_opportunities: 0,
              top_scored: [],
              closing_soon: [],
              status_breakdown: [],
              country_breakdown: [],
              degraded_sources: 0,
              failing_sources: 0,
              source_alerts: [],
              data_coverage: { with_summary: 0, with_amount: 0, with_close_date: 0, with_source: 0, embeddings_coverage: null },
              profile: { completeness: 0, missing_fields: [] },
            }),
            { status: 200 },
          ),
        );
      }),
    );

    const { api } = await loadApiModule();
    const result = await api.dashboardSummary();
    expect(capturedUrls).toHaveLength(1);
    expect(capturedUrls[0]).toMatch(/\/dashboard\/summary$/);
    expect(result.data_coverage.embeddings_coverage).toBeNull();
  });
});

/**
 * PR 3 (tier-2-production-readiness): 401 discrimination by request path.
 *
 * `/auth/*` 401s are real auth failures (wrong password, expired reset
 * token, etc.) — the frontend must surface the server's detail and NOT
 * auto-redirect. Other 401s mean our session is stale — redirect to /login.
 *
 * (The companion env-var fallback tests live in __tests__/api-env.test.ts
 * so each commit stays atomic.)
 */

describe("PR 3 — 401 discrimination by request path", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "development");
    if (typeof window !== "undefined") {
      window.localStorage.clear();
    }
  });

  it("throws the server's body.detail on 401 for /auth/login (no redirect)", async () => {
    const replaceSpy = vi.fn();
    // window.location.replace is the navigation entry-point used by
    // handleUnauthorized. We spy on it to assert "no redirect happened".
    const originalReplace = window.location.replace;
    window.location.replace = replaceSpy as typeof window.location.replace;
    try {
      vi.stubGlobal(
        "fetch",
        vi.fn(() =>
          Promise.resolve(
            new Response(JSON.stringify({ detail: "Invalid credentials" }), {
              status: 401,
              headers: { "Content-Type": "application/json" },
            }),
          ),
        ),
      );

      const { api } = await loadApiModule();
      await expect(api.login("user@example.com", "wrong-password")).rejects.toThrow(
        "Invalid credentials",
      );
      expect(replaceSpy).not.toHaveBeenCalled();
    } finally {
      window.location.replace = originalReplace;
    }
  });

  it("throws 'Credenciales inválidas' on 401 for /auth/login with empty body.detail", async () => {
    const replaceSpy = vi.fn();
    const originalReplace = window.location.replace;
    window.location.replace = replaceSpy as typeof window.location.replace;
    try {
      vi.stubGlobal(
        "fetch",
        vi.fn(() =>
          Promise.resolve(
            new Response(JSON.stringify({}), {
              status: 401,
              headers: { "Content-Type": "application/json" },
            }),
          ),
        ),
      );

      const { api } = await loadApiModule();
      await expect(api.login("user@example.com", "wrong-password")).rejects.toThrow(
        "Credenciales inválidas",
      );
      expect(replaceSpy).not.toHaveBeenCalled();
    } finally {
      window.location.replace = originalReplace;
    }
  });

  it("throws body.detail on 401 for /auth/forgot-password (any /auth/* path)", async () => {
    const replaceSpy = vi.fn();
    const originalReplace = window.location.replace;
    window.location.replace = replaceSpy as typeof window.location.replace;
    try {
      vi.stubGlobal(
        "fetch",
        vi.fn(() =>
          Promise.resolve(
            new Response(
              JSON.stringify({ detail: "Reset token is invalid or expired" }),
              { status: 401, headers: { "Content-Type": "application/json" } },
            ),
          ),
        ),
      );

      const { request } = await loadApiModule();
      await expect(
        request("/auth/reset-password", {
          method: "POST",
          body: JSON.stringify({ token: "x", new_password: "longenough123" }),
        }),
      ).rejects.toThrow("Reset token is invalid or expired");
      expect(replaceSpy).not.toHaveBeenCalled();
    } finally {
      window.location.replace = originalReplace;
    }
  });

  it("redirects and throws 'Sesión expirada...' on 401 for non-auth paths (e.g. /me)", async () => {
    const replaceSpy = vi.fn();
    const originalReplace = window.location.replace;
    window.location.replace = replaceSpy as typeof window.location.replace;
    try {
      vi.stubGlobal(
        "fetch",
        vi.fn(() =>
          Promise.resolve(
            new Response(JSON.stringify({ detail: "Not authenticated" }), {
              status: 401,
              headers: { "Content-Type": "application/json" },
            }),
          ),
        ),
      );

      const { api } = await loadApiModule();
      await expect(api.me()).rejects.toThrow(
        "Sesión expirada. Redirigiendo al inicio de sesión.",
      );
      // handleUnauthorized MUST have redirected to /login.
      expect(replaceSpy).toHaveBeenCalledWith("/login");
    } finally {
      window.location.replace = originalReplace;
    }
  });

  it("unchanged: throws body.detail on 500 (not affected by 401 split)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ detail: "Internal server error" }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );

    const { api } = await loadApiModule();
    await expect(api.me()).rejects.toThrow("Internal server error");
  });
});
