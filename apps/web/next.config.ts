import type { NextConfig } from "next";
import path from "node:path";

let nextConfig: NextConfig = {
  basePath: "/observatorio",
  skipTrailingSlashRedirect: true,
  // Standalone output: produces a self-contained server at .next/standalone with
  // only the deps the app actually needs, ideal for slim Docker images.
  output: "standalone",
  typedRoutes: false,
  turbopack: {
    root: path.resolve(__dirname, "../.."),
  },
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "www.colmayor.edu.co",
        pathname: "/wp-content/uploads/**",
      },
    ],
  },
  // SEC-REMEDIATION-T4: security headers on every response (mirrors the
  // API middleware). Deliberately no page-level CSP: Next injects inline
  // flight data (__next_f) that a strict CSP would break.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains",
          },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
  // Browser traffic can use a same-origin public URL such as /api/v1, while
  // the Next.js server always proxies to the private Docker-network endpoint.
  // Keeping the two concerns separate prevents Docker hostnames from leaking
  // into the client bundle and avoids localhost assumptions inside containers.
  async rewrites() {
    const internalApiUrl =
      process.env.INTERNAL_API_URL?.replace(/\/$/, "") || "http://api:8000/api/v1";

    return [
      {
        source: "/api/v1/:path*",
        destination: `${internalApiUrl}/:path*`,
      },
    ];
  },
};

// Conditionally wrap with bundle-analyzer when ANALYZE=true
if (process.env.ANALYZE === "true") {
  const withBundleAnalyzer = require("@next/bundle-analyzer")({ enabled: true });
  nextConfig = withBundleAnalyzer(nextConfig);
}

export default nextConfig;
