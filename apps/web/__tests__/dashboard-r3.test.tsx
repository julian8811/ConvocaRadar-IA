/**
 * R3 (panel-reestructurado): restructure home — sin duplicadas, tabs
 * condicionales, matriz con empty-state y título dinámico.
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
const mockDashboardHealth = vi.fn();
const mockFaculties = vi.fn();
const mockAxes = vi.fn();
const mockFacultyMatrix = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    dashboardTriage: (...args: unknown[]) => mockDashboardTriage(...args),
    dashboardHealth: (...args: unknown[]) => mockDashboardHealth(...args),
    faculties: (...args: unknown[]) => mockFaculties(...args),
    axes: (...args: unknown[]) => mockAxes(...args),
    facultyMatrix: (...args: unknown[]) => mockFacultyMatrix(...args),
  },
}));

vi.mock("lucide-react", () => {
  const Stub: React.FC<{ className?: string }> = (props) => <svg data-testid="icon-stub" className={props.className} />;
  return {
    Activity: Stub,
    AlertTriangle: Stub,
    ArrowRight: Stub,
    CalendarClock: Stub,
    Clock: Stub,
    Database: Stub,
    Globe: Stub,
    ListChecks: Stub,
    Sparkles: Stub,
    Target: Stub,
    TrendingUp: Stub,
  };
});

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

function triageItem(id: string) {
  return { id, title: `Conv ${id}`, country: "Colombia", currency: "COP", funding_amount: null, days_to_close: 3, score: 60, source_key: "s1" };
}

function healthPayload(overrides: Record<string, unknown> = {}) {
  return {
    kpis: { total: 10, open: 8, closing_soon: 2, high_match: 1 },
    data_coverage: { with_summary: 1, with_amount: 1, with_close_date: 1, with_source: 1, embeddings_coverage: 50 },
    status_breakdown: [{ name: "open", total: 8 }],
    country_breakdown: [{ name: "Colombia", total: 8 }],
    sources_health: [],
    failing_sources: 0,
    degraded_sources: 0,
    source_alerts: [],
    score_distribution: [],
    funding_ranges: [],
    source_contribution: [],
    opportunities_timeline: [],
    category_distribution: [],
    ...overrides,
  };
}

describe("R3 TriageZone", () => {
  beforeEach(() => {
    mockDashboardTriage.mockReset();
  });

  it("sin tarjetas duplicadas: no muestra Atención inmediata ni Prioridades visibles", async () => {
    mockDashboardTriage.mockResolvedValue({ review_queue: [triageItem("1")], closing_soon_7d: [triageItem("2")] });
    const { TriageZone } = await import("@/components/dashboard/TriageZone");
    const Wrapper = makeWrapper();
    render(<Wrapper><TriageZone /></Wrapper>);
    await waitFor(() => {
      expect(screen.getByText(/qué hago hoy/i)).toBeDefined();
    });
    expect(screen.queryByText(/atención inmediata/i)).toBeNull();
    expect(screen.queryByText(/prioridades visibles/i)).toBeNull();
    expect(screen.queryByText(/en seguimiento/i)).toBeNull();
  });

  it("usa la definición única: Cierran en 7 días", async () => {
    mockDashboardTriage.mockResolvedValue({ review_queue: [], closing_soon_7d: [triageItem("2")] });
    const { TriageZone } = await import("@/components/dashboard/TriageZone");
    const Wrapper = makeWrapper();
    render(<Wrapper><TriageZone /></Wrapper>);
    await waitFor(() => {
      expect(screen.getAllByText(/cierran en 7 días/i).length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.queryByText(/próximos cierres/i)).toBeNull();
  });
});

describe("R3 HealthZone", () => {
  beforeEach(() => {
    mockDashboardHealth.mockReset();
  });

  it("KPIs con los 4 rótulos aprobados", async () => {
    mockDashboardHealth.mockResolvedValue(healthPayload());
    const { HealthZone } = await import("@/components/dashboard/HealthZone");
    const Wrapper = makeWrapper();
    render(<Wrapper><HealthZone /></Wrapper>);
    await waitFor(() => {
      expect(screen.getByText(/^total$/i)).toBeDefined();
    });
    expect(screen.getByText(/^abiertas$/i)).toBeDefined();
    expect(screen.getByText(/cierran en 7 días/i)).toBeDefined();
    expect(screen.getByText(/alta compatibilidad/i)).toBeDefined();
    expect(screen.queryByText(/cierran pronto/i)).toBeNull();
  });

  it("oculta tabs Score/Financiación/Categorías sin datos; muestra Estado/País", async () => {
    mockDashboardHealth.mockResolvedValue(healthPayload());
    const { HealthZone } = await import("@/components/dashboard/HealthZone");
    const Wrapper = makeWrapper();
    render(<Wrapper><HealthZone /></Wrapper>);
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /^estado$/i })).toBeDefined();
    });
    expect(screen.getByRole("tab", { name: /^país$/i })).toBeDefined();
    expect(screen.queryByRole("tab", { name: /compatibilidad/i })).toBeNull();
    expect(screen.queryByRole("tab", { name: /financiación/i })).toBeNull();
    expect(screen.queryByRole("tab", { name: /categorías/i })).toBeNull();
  });

  it("muestra el tab Compatibilidad cuando hay datos", async () => {
    mockDashboardHealth.mockResolvedValue(healthPayload({ score_distribution: [{ name: "60-70", total: 3 }] }));
    const { HealthZone } = await import("@/components/dashboard/HealthZone");
    const Wrapper = makeWrapper();
    render(<Wrapper><HealthZone /></Wrapper>);
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /compatibilidad/i })).toBeDefined();
    });
  });

  it("tabla Salud de fuentes: solo degraded/failing, sin sanas ni idle", async () => {
    const base = { health_score: 50, health_status: "degraded", tier: null, auto_paused: false, key: "k" };
    mockDashboardHealth.mockResolvedValue(healthPayload({
      degraded_sources: 1,
      failing_sources: 1,
      sources_health: [
        { ...base, source_id: "d1", name: "Degradada Uno", status: "degraded" },
        { ...base, source_id: "f1", name: "Falla Uno", status: "failing" },
        { ...base, source_id: "h1", name: "Sana Uno", status: "healthy", health_score: 99, health_status: "healthy" },
        { ...base, source_id: "i1", name: "Idle Uno", status: "idle", health_score: 10, health_status: "stable" },
      ],
    }));
    const { HealthZone } = await import("@/components/dashboard/HealthZone");
    const Wrapper = makeWrapper();
    render(<Wrapper><HealthZone /></Wrapper>);
    await waitFor(() => {
      expect(screen.getByText("Degradada Uno")).toBeDefined();
    });
    expect(screen.getByText("Falla Uno")).toBeDefined();
    expect(screen.queryByText("Sana Uno")).toBeNull();
    expect(screen.queryByText("Idle Uno")).toBeNull();
  });

  it("sin fuentes con problema: ni banner ni tabla", async () => {
    mockDashboardHealth.mockResolvedValue(healthPayload());
    const { HealthZone } = await import("@/components/dashboard/HealthZone");
    const Wrapper = makeWrapper();
    render(<Wrapper><HealthZone /></Wrapper>);
    await waitFor(() => {
      expect(screen.getByText(/^total$/i)).toBeDefined();
    });
    expect(screen.queryByText(/requieren atención/i)).toBeNull();
    expect(screen.queryByText(/^salud de fuentes$/i)).toBeNull();
  });
});

describe("R3 FacultyMatrix", () => {
  beforeEach(() => {
    mockFaculties.mockReset();
    mockAxes.mockReset();
    mockFacultyMatrix.mockReset();
  });

  function mockAllZero() {
    mockFaculties.mockResolvedValue({ faculties: [{ id: "f1", key: "F1", color: "#000" }] });
    mockAxes.mockResolvedValue({ axes: [{ id: "a1", label: "Eje 1" }] });
    mockFacultyMatrix.mockResolvedValue({ cells: [{ faculty_id: "f1", axis_id: "a1", count: 0 }], total: 0 });
  }

  it("empty-state Matching aún no ejecutado si todo en 0, con título dinámico", async () => {
    mockAllZero();
    const { FacultyMatrix } = await import("@/components/faculty/FacultyMatrix");
    const Wrapper = makeWrapper();
    render(<Wrapper><FacultyMatrix /></Wrapper>);
    await waitFor(() => {
      expect(screen.getByText(/matching aún no ejecutado/i)).toBeDefined();
    });
    expect(screen.getByText(/matriz facultades × ejes \(1×1\)/i)).toBeDefined();
    expect(screen.queryByText(/4×6/i)).toBeNull();
  });

  it("renderiza conteos con título derivado de los datos", async () => {
    mockFaculties.mockResolvedValue({ faculties: [{ id: "f1", key: "F1", color: "#000" }, { id: "f2", key: "F2", color: "#111" }] });
    mockAxes.mockResolvedValue({ axes: [{ id: "a1", label: "Eje 1" }] });
    mockFacultyMatrix.mockResolvedValue({ cells: [{ faculty_id: "f1", axis_id: "a1", count: 5 }], total: 5 });
    const { FacultyMatrix } = await import("@/components/faculty/FacultyMatrix");
    const Wrapper = makeWrapper();
    render(<Wrapper><FacultyMatrix /></Wrapper>);
    await waitFor(() => {
      expect(screen.getByText(/matriz facultades × ejes \(2×1\)/i)).toBeDefined();
    });
    expect(screen.queryByText(/matching aún no ejecutado/i)).toBeNull();
  });
});
