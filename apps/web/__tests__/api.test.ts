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
