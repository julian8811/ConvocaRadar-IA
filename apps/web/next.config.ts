import type { NextConfig } from "next";
import path from "node:path";

let nextConfig: NextConfig = {
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
  // Proxy /api/v1 requests to the internal API service so both SSR and
  // client-side calls work without exposing the Docker hostname.
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://api:8000/api/v1"}/:path*`,
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
