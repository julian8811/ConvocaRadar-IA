/**
 * SEC-REMEDIATION-T4: security headers on every Next response.
 *
 * Mirrors the API middleware policy (HSTS, nosniff, DENY, referrer,
 * permissions). Deliberately NO page-level CSP: Next injects inline
 * flight data (__next_f) that a strict CSP would break.
 *
 * RED test: fails until next.config.ts exposes async headers().
 */
import { describe, expect, it } from "vitest";

import nextConfig from "../next.config";

const EXPECTED: Record<string, string> = {
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
};

describe("next.config headers() — security headers", () => {
  it("exposes headers() covering /:path* with the API-mirrored policy", async () => {
    const headersFn = nextConfig.headers;
    expect(headersFn, "next.config must expose async headers()").toBeDefined();
    if (!headersFn) throw new Error("headers() missing");
    const rules = await headersFn();
    const rule = rules.find((r) => r.source === "/:path*");
    expect(rule, 'expected a headers rule with source "/:path*"').toBeDefined();
    if (!rule) throw new Error("rule missing");
    const got: Record<string, string> = {};
    for (const h of rule.headers) got[h.key] = h.value;
    for (const [key, value] of Object.entries(EXPECTED)) {
      expect(got[key], `missing/incorrect header ${key}`).toBe(value);
    }
  });

  it("does not set a page-level CSP (would break Next flight data)", async () => {
    const headersFn = nextConfig.headers;
    if (!headersFn) throw new Error("headers() missing");
    const rules = await headersFn();
    for (const rule of rules) {
      const keys = rule.headers.map((h) => h.key.toLowerCase());
      expect(keys, `rule ${rule.source} must not set CSP`).not.toContain(
        "content-security-policy",
      );
    }
  });
});
