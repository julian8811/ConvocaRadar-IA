/**
 * PR B-2 (dashboard-redesign): Vitest component tests for the new 3-zone
 * dashboard layout.
 *
 * Each zone (Triage / Pipeline / Health) is a self-contained React
 * component that owns its own useQuery call. The page just composes them
 * top-to-bottom. Each zone renders a per-section skeleton while loading
 * and an error state when its own API call fails.
 *
 * This test file is the RED step of WU-B2-1: it imports the production
 * components that DO NOT EXIST YET. The test will fail to import.
 * WU-B2-5 (skeletons) and WU-B2-6 (zones) GREEN it by exporting the
 * components.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type ReactNode } from "react";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

vi.mock("next/link", () => ({
  default: ({ children, ...props }: { children: React.ReactNode; href: string }) =>
    <a {...props}>{children}</a>,
}));

const mockDashboardTriage = vi.fn();
const mockDashboardPipeline = vi.fn();
const mockDashboardHealth = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    dashboardTriage: (...args: unknown[]) => mockDashboardTriage(...args),
    dashboardPipeline: (...args: unknown[]) => mockDashboardPipeline(...args),
    dashboardHealth: (...args: unknown[]) => mockDashboardHealth(...args),
  },
}));

// Explicit lucide-react stub: avoid Proxy to prevent infinite loops.
vi.mock("lucide-react", () => {
  const Stub: React.FC<{ className?: string }> = (props) => <svg data-testid="icon-stub" className={props.className} />;
  return {
    AlertCircle: Stub,
    AlertTriangle: Stub,
    CalendarClock: Stub,
    Database: Stub,
    FileText: Stub,
    Gauge: Stub,
    Heart: Stub,
    Loader2: Stub,
    MapPinned: Stub,
    Radar: Stub,
    Sparkles: Stub,
    Target: Stub,
    TrendingUp: Stub,
    ListChecks: Stub,
    Check: Stub,
    ArrowRight: Stub,
  };
});

// Charts are now Recharts-based. The barrel import at
// @/components/dashboard/charts resolves to the new Recharts components.
// We stub the barrel so HealthZone doesn't need the full Recharts SVG
// rendering in happy-dom.
vi.mock("@/components/dashboard/charts", () => ({
  StatusChart: () => <div data-testid="recharts-status-chart" />,
  CountryChart: () => <div data-testid="recharts-country-chart" />,
  ScoreChart: () => <div data-testid="recharts-score-chart" />,
  FundingChart: () => <div data-testid="recharts-funding-chart" />,
  SourceChart: () => <div data-testid="recharts-source-chart" />,
  CategoryChart: () => <div data-testid="recharts-category-chart" />,
}));

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, retryDelay: 0 } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

/**
 * Helper: build a "loading" promise that never resolves. The default
 * behavior of useQuery with no data is to render a skeleton.
 */
function pendingPromise<T>(): Promise<T> {
  return new Promise<T>(() => {});
}

describe("Dashboard 3-zone structure (PR B-2)", () => {
  beforeEach(() => {
    mockDashboardTriage.mockReset();
    mockDashboardPipeline.mockReset();
    mockDashboardHealth.mockReset();
  });

  it("renders three distinct zones in the Triage -> Pipeline -> Health order", async () => {
    // Resolve all 3 queries with empty data so each zone renders its
    // content (including the zone marker heading) rather than a skeleton.
    mockDashboardTriage.mockResolvedValue({
      review_queue: [],
      closing_soon_7d: [],
      profile: { completeness: 0, missing_fields: [] },
    });
    mockDashboardPipeline.mockResolvedValue({ top_scored: [], closing_soon: [] });
    mockDashboardHealth.mockResolvedValue({
      kpis: { total: 0, open: 0, closing_soon: 0, high_match: 0 },
      data_coverage: { with_summary: 0, with_amount: 0, with_close_date: 0, with_source: 0, embeddings_coverage: null },
      status_breakdown: [],
      country_breakdown: [],
      sources_health: [],
      failing_sources: 0,
      degraded_sources: 0,
      source_alerts: [],
      score_distribution: [],
      funding_ranges: [],
      source_contribution: [],
      opportunities_timeline: [],
      category_distribution: [],
    });

    const DashboardPage = (await import("@/app/(app)/dashboard/page")).default;
    const Wrapper = makeWrapper();
    const { container } = render(
      <Wrapper>
        <DashboardPage />
      </Wrapper>,
    );

    // Each zone must render its own title (zone marker).
    await waitFor(() => {
      expect(screen.getByText(/qu[ée]\s+hago\s+hoy/i)).toBeDefined();
    });
    expect(screen.getByText(/mi cola de revisión/i)).toBeDefined();
    expect(screen.getByText(/estado de convocatorias/i)).toBeDefined();

    // DOM order: Triage zone appears before Pipeline zone appears before Health zone.
    const triageHeading = screen.getByText(/qu[ée]\s+hago\s+hoy/i);
    const pipelineHeading = screen.getByText(/mi cola de revisión/i);
    const healthHeading = screen.getByText(/estado de convocatorias/i);
    expect(
      triageHeading.compareDocumentPosition(pipelineHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      pipelineHeading.compareDocumentPosition(healthHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(container).toBeDefined();
  });

  it("fires the three queries in parallel (no full-page blocking load)", async () => {
    let resolveTriage: (v: unknown) => void = () => {};
    let resolvePipeline: (v: unknown) => void = () => {};
    let resolveHealth: (v: unknown) => void = () => {};
    mockDashboardTriage.mockReturnValue(
      new Promise((res) => {
        resolveTriage = res;
      }),
    );
    mockDashboardPipeline.mockReturnValue(
      new Promise((res) => {
        resolvePipeline = res;
      }),
    );
    mockDashboardHealth.mockReturnValue(
      new Promise((res) => {
        resolveHealth = res;
      }),
    );

    const DashboardPage = (await import("@/app/(app)/dashboard/page")).default;
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <DashboardPage />
      </Wrapper>,
    );

    // All three fetches must have been initiated before any resolve.
    await waitFor(() => {
      expect(mockDashboardTriage).toHaveBeenCalledTimes(1);
    });
    expect(mockDashboardPipeline).toHaveBeenCalledTimes(1);
    expect(mockDashboardHealth).toHaveBeenCalledTimes(1);

    // Resolve all so the test cleanup is clean.
    resolveTriage({ kpis: { total_opportunities: 0 }, closing_soon_7d: [], review_queue: [], profile: { completeness: 0, missing_fields: [] } });
    resolvePipeline({ top_scored: [], closing_soon: [], review_queue: [] });
    resolveHealth({ kpis: { total: 0, open: 0, closing_soon: 0, high_match: 0 }, data_coverage: { with_summary: 0, with_amount: 0, with_close_date: 0, with_source: 0, embeddings_coverage: null }, status_breakdown: [], country_breakdown: [], sources_health: [], failing_sources: 0, degraded_sources: 0, source_alerts: [], score_distribution: [], funding_ranges: [], source_contribution: [], opportunities_timeline: [], category_distribution: [] });
  });

  it("renders a skeleton per zone while each query is loading (no full-page LoadingState)", async () => {
    mockDashboardTriage.mockReturnValue(pendingPromise());
    mockDashboardPipeline.mockReturnValue(pendingPromise());
    mockDashboardHealth.mockReturnValue(pendingPromise());

    const DashboardPage = (await import("@/app/(app)/dashboard/page")).default;
    const Wrapper = makeWrapper();
    const { container } = render(
      <Wrapper>
        <DashboardPage />
      </Wrapper>,
    );

    // Three distinct skeleton elements must be present (one per zone).
    // Each skeleton carries data-zone-skeleton="triage|pipeline|health".
    await waitFor(() => {
      const skeletons = container.querySelectorAll("[data-zone-skeleton]");
      expect(skeletons.length).toBe(3);
    });
  });
});

describe("TriageZone", () => {
  beforeEach(() => {
    mockDashboardTriage.mockReset();
  });

  it("calls api.dashboardTriage on mount", async () => {
    mockDashboardTriage.mockReturnValue(pendingPromise());

    const { TriageZone } = await import("@/components/dashboard/TriageZone");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <TriageZone />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(mockDashboardTriage).toHaveBeenCalledTimes(1);
    });
  });

  it("renders a skeleton while loading", async () => {
    mockDashboardTriage.mockReturnValue(pendingPromise());

    const { TriageZone } = await import("@/components/dashboard/TriageZone");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <TriageZone />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("triage-skeleton")).toBeDefined();
    });
  });

  it("renders an error state when the API call fails", async () => {
    mockDashboardTriage.mockRejectedValue(new Error("network down"));

    const { TriageZone } = await import("@/components/dashboard/TriageZone");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <TriageZone />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText(/network down/i)).toBeDefined();
    });
  });
});

describe("PipelineZone", () => {
  beforeEach(() => {
    mockDashboardPipeline.mockReset();
  });

  it("calls api.dashboardPipeline on mount", async () => {
    mockDashboardPipeline.mockReturnValue(pendingPromise());

    const { PipelineZone } = await import("@/components/dashboard/PipelineZone");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <PipelineZone />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(mockDashboardPipeline).toHaveBeenCalledTimes(1);
    });
  });

  it("renders a skeleton while loading", async () => {
    mockDashboardPipeline.mockReturnValue(pendingPromise());

    const { PipelineZone } = await import("@/components/dashboard/PipelineZone");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <PipelineZone />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("pipeline-skeleton")).toBeDefined();
    });
  });

  it("renders an error state when the API call fails", async () => {
    mockDashboardPipeline.mockRejectedValue(new Error("pipeline failed"));

    const { PipelineZone } = await import("@/components/dashboard/PipelineZone");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <PipelineZone />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText(/pipeline failed/i)).toBeDefined();
    });
  });
});

describe("HealthZone", () => {
  beforeEach(() => {
    mockDashboardHealth.mockReset();
  });

  it("calls api.dashboardHealth on mount", async () => {
    mockDashboardHealth.mockReturnValue(pendingPromise());

    const { HealthZone } = await import("@/components/dashboard/HealthZone");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <HealthZone />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(mockDashboardHealth).toHaveBeenCalledTimes(1);
    });
  });

  it("renders a skeleton while loading", async () => {
    mockDashboardHealth.mockReturnValue(pendingPromise());

    const { HealthZone } = await import("@/components/dashboard/HealthZone");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <HealthZone />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("health-skeleton")).toBeDefined();
    });
  });

  it("renders an error state when the API call fails", async () => {
    mockDashboardHealth.mockRejectedValue(new Error("health failed"));

    const { HealthZone } = await import("@/components/dashboard/HealthZone");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <HealthZone />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText(/health failed/i)).toBeDefined();
    });
  });

  it("renders 'Sin datos aún' when data_coverage.embeddings_coverage is null (no 0%)", async () => {
    mockDashboardHealth.mockResolvedValue({
      kpis: { total: 0, open: 0, closing_soon: 0, high_match: 0 },
      data_coverage: {
        with_summary: 0,
        with_amount: 0,
        with_close_date: 0,
        with_source: 0,
        embeddings_coverage: null,
      },
      status_breakdown: [],
      country_breakdown: [],
      sources_health: [],
      failing_sources: 0,
      degraded_sources: 0,
      source_alerts: [],
    });

    const { HealthZone } = await import("@/components/dashboard/HealthZone");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <HealthZone />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText(/sin datos a[uú]n/i)).toBeDefined();
    });
  });
});
