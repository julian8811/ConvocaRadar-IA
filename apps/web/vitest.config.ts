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
    setupFiles: ["./vitest.setup.ts"],
    // SEC-RENDER-STARTUP: request() retry mechanism now delays up to ~91s.
    // Increase testTimeout so the TypeError retry test doesn't time out.
    testTimeout: 120_000,
  },
});
