import type { NextConfig } from "next";
import path from "node:path";

let nextConfig: NextConfig = {
  typedRoutes: false,
  turbopack: {
    root: path.resolve(__dirname, "../.."),
  },
};

// Conditionally wrap with bundle-analyzer when ANALYZE=true
if (process.env.ANALYZE === "true") {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const withBundleAnalyzer = require("@next/bundle-analyzer")({
    enabled: true,
  });
  nextConfig = withBundleAnalyzer(nextConfig);
}

export default nextConfig;
