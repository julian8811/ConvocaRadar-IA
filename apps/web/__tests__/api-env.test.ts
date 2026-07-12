/**
 * PR 3 (tier-2-production-readiness): API_URL env-var fallback.
 *
 * The original `?? getDefaultApiUrl()` was wrong because Vercel allows
 * setting an env var to "" without deleting it, and `??` only falls back
 * on nullish (null/undefined), NOT on empty string. This causes the
 * production bundle to ship with `API_URL=""` and every request fails
 * with a network error.
 *
 * Fix: use `||` instead of `??` so the empty string also triggers the
 * fallback to `getDefaultApiUrl()`.
 *
 * As of the SameSite fix, the production fallback has been removed:
 * `getDefaultApiUrl()` returns `""` when not on localhost, so missing
 * or empty NEXT_PUBLIC_API_URL yields `API_URL=""` — a fail-fast signal
 * that the env var must be set explicitly.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

const EXPECTED_DEFAULT_API_URL = "";

async function loadApiModule() {
  vi.resetModules();
  return import("@/lib/api");
}

describe("API_URL — env-var fallback", () => {
  beforeEach(() => {
    // happy-dom defaults hostname to "localhost" which would make
    // getDefaultApiUrl() return the dev URL. Stub it so the default
    // matches the production behaviour: no fallback URL.
    Object.defineProperty(window.location, "hostname", {
      value: "app.example.com",
      writable: true,
      configurable: true,
    });
  });

  it("returns empty string when NEXT_PUBLIC_API_URL is empty (fail-fast)", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "");
    const { API_URL } = await loadApiModule();
    expect(API_URL).toBe("");
  });

  it("returns empty string when NEXT_PUBLIC_API_URL is undefined (fail-fast)", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", undefined);
    const { API_URL } = await loadApiModule();
    expect(API_URL).toBe("");
  });

  it("uses the env value when NEXT_PUBLIC_API_URL is a non-empty string", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com/api/v1");
    const { API_URL } = await loadApiModule();
    expect(API_URL).toBe("https://api.example.com/api/v1");
  });

  it("strips a trailing slash from NEXT_PUBLIC_API_URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com/api/v1/");
    const { API_URL } = await loadApiModule();
    expect(API_URL).toBe("https://api.example.com/api/v1");
  });
});
