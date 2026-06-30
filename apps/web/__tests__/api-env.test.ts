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
 * fallback to the default URL.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

/**
 * The "default" URL the module falls back to when no env var is set.
 * `getDefaultApiUrl()` is not exported, but it returns the production
 * URL when `window.location.hostname` is NOT `localhost` or `127.0.0.1`.
 * happy-dom defaults hostname to "localhost" so we stub it for these
 * tests to make the assertion deterministic.
 */
const EXPECTED_DEFAULT_API_URL = "https://api.convocaradar.com/api/v1";

async function loadApiModule() {
  vi.resetModules();
  return import("@/lib/api");
}

describe("PR 3 — API_URL env-var fallback (?? → ||)", () => {
  beforeEach(() => {
    // happy-dom defaults hostname to "localhost" which would make
    // getDefaultApiUrl() return the dev URL. Stub it so the default
    // matches the production URL we're asserting against.
    Object.defineProperty(window.location, "hostname", {
      value: "app.example.com",
      writable: true,
      configurable: true,
    });
  });

  it("falls back to the default URL when NEXT_PUBLIC_API_URL is the empty string", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "");
    const { API_URL } = await loadApiModule();
    expect(API_URL).toBe(EXPECTED_DEFAULT_API_URL);
  });

  it("falls back to the default URL when NEXT_PUBLIC_API_URL is unset (undefined)", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", undefined);
    const { API_URL } = await loadApiModule();
    expect(API_URL).toBe(EXPECTED_DEFAULT_API_URL);
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
