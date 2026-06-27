import { defineConfig } from "vitest/config";

import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(__dirname, "."),
    },
  },
  test: {
    include: ["**/*.{test,spec}.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", ".next/**"],
    passWithNoTests: true,
    css: false,
    environment: "happy-dom",
    setupFiles: [],
  },
});
