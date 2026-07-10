// Mock ResizeObserver for Recharts ResponsiveContainer in happy-dom
// If ResizeObserver is not available, Recharts cannot compute dimensions.
if (typeof ResizeObserver === "undefined") {
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
    ResizeObserverMock;
}
