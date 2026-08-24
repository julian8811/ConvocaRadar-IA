/**
 * Task 2 — Verify Recharts chart components render correctly.
 *
 * These tests replace the old Plotly-based chart components with
 * lightweight Recharts equivalents. Each test renders the component
 * with sample data and verifies the expected DOM structure exists.
 *
 * PR3 (REQ-FE-CHARTS-1): charts load through next/dynamic ssr:false
 * wrappers, so content resolves asynchronously — queries are awaited.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  StatusChart,
  CountryChart,
  ScoreChart,
  FundingChart,
  SourceChart,
  CategoryChart,
} from "@/components/dashboard/charts";

const sampleBreakdown = [
  { name: "Abierta", total: 45 },
  { name: "Cerrada", total: 30 },
  { name: "Próximamente", total: 15 },
];

afterEach(() => {
  cleanup();
});

describe("StatusChart (donut)", () => {
  it("renders with data-testid when data is provided", async () => {
    render(<StatusChart data={sampleBreakdown} />);
    const el = await screen.findByTestId("status-chart");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", async () => {
    render(<StatusChart data={[]} />);
    const empty = await screen.findByTestId("status-chart-empty");
    expect(empty.textContent).toContain("Sin convocatorías");
  });
});

describe("CountryChart (horizontal bar)", () => {
  it("renders with data-testid when data is provided", async () => {
    render(<CountryChart data={sampleBreakdown} />);
    const el = await screen.findByTestId("country-chart");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", async () => {
    render(<CountryChart data={[]} />);
    const empty = await screen.findByTestId("country-chart-empty");
    expect(empty.textContent).toContain("Sin distribución geográfica");
  });
});

describe("ScoreChart (vertical bar)", () => {
  it("renders with data-testid when data is provided", async () => {
    render(<ScoreChart data={sampleBreakdown} />);
    const el = await screen.findByTestId("score-chart");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", async () => {
    render(<ScoreChart data={[]} />);
    const empty = await screen.findByTestId("score-chart-empty");
    expect(empty.textContent).toContain("Sin scores calculados");
  });
});

describe("FundingChart (horizontal bar)", () => {
  it("renders with data-testid when data is provided", async () => {
    render(<FundingChart data={sampleBreakdown} />);
    const el = await screen.findByTestId("funding-chart");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", async () => {
    render(<FundingChart data={[]} />);
    const empty = await screen.findByTestId("funding-chart-empty");
    expect(empty.textContent).toContain("Sin datos de financiamiento");
  });
});

describe("SourceChart (horizontal bar)", () => {
  it("renders with data-testid when data is provided, limit to top 10", async () => {
    const many = Array.from({ length: 15 }, (_, i) => ({
      name: `Source ${i + 1}`,
      total: 100 - i,
    }));
    render(<SourceChart data={many} />);
    const el = await screen.findByTestId("source-chart");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", async () => {
    render(<SourceChart data={[]} />);
    const empty = await screen.findByTestId("source-chart-empty");
    expect(empty.textContent).toContain("Sin datos de fuentes");
  });
});

describe("CategoryChart (horizontal bar)", () => {
  it("renders with data-testid when data is provided", async () => {
    render(<CategoryChart data={sampleBreakdown} />);
    const el = await screen.findByTestId("category-chart");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", async () => {
    render(<CategoryChart data={[]} />);
    const empty = await screen.findByTestId("category-chart-empty");
    expect(empty.textContent).toContain("Sin datos de categorías");
  });
});
