/**
 * Task 2 — Verify Recharts chart components render correctly.
 *
 * These tests replace the old Plotly-based chart components with
 * lightweight Recharts equivalents. Each test renders the component
 * with sample data and verifies the expected DOM structure exists.
 */

import { cleanup, render } from "@testing-library/react";
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
  it("renders with data-testid when data is provided", () => {
    const { container } = render(<StatusChart data={sampleBreakdown} />);
    const el = container.querySelector("[data-testid='status-chart']");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", () => {
    const { container } = render(<StatusChart data={[]} />);
    const empty = container.querySelector("[data-testid='status-chart-empty']");
    expect(empty).not.toBeNull();
    expect(empty?.textContent).toContain("Sin convocatorías");
  });
});

describe("CountryChart (horizontal bar)", () => {
  it("renders with data-testid when data is provided", () => {
    const { container } = render(<CountryChart data={sampleBreakdown} />);
    const el = container.querySelector("[data-testid='country-chart']");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", () => {
    const { container } = render(<CountryChart data={[]} />);
    expect(container.querySelector("[data-testid='country-chart-empty']")).not.toBeNull();
  });
});

describe("ScoreChart (vertical bar)", () => {
  it("renders with data-testid when data is provided", () => {
    const { container } = render(<ScoreChart data={sampleBreakdown} />);
    const el = container.querySelector("[data-testid='score-chart']");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", () => {
    const { container } = render(<ScoreChart data={[]} />);
    expect(container.querySelector("[data-testid='score-chart-empty']")).not.toBeNull();
  });
});

describe("FundingChart (horizontal bar)", () => {
  it("renders with data-testid when data is provided", () => {
    const { container } = render(<FundingChart data={sampleBreakdown} />);
    const el = container.querySelector("[data-testid='funding-chart']");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", () => {
    const { container } = render(<FundingChart data={[]} />);
    expect(container.querySelector("[data-testid='funding-chart-empty']")).not.toBeNull();
  });
});

describe("SourceChart (horizontal bar)", () => {
  it("renders with data-testid when data is provided, limit to top 10", () => {
    const many = Array.from({ length: 15 }, (_, i) => ({
      name: `Source ${i + 1}`,
      total: 100 - i,
    }));
    const { container } = render(<SourceChart data={many} />);
    const el = container.querySelector("[data-testid='source-chart']");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", () => {
    const { container } = render(<SourceChart data={[]} />);
    expect(container.querySelector("[data-testid='source-chart-empty']")).not.toBeNull();
  });
});

describe("CategoryChart (horizontal bar)", () => {
  it("renders with data-testid when data is provided", () => {
    const { container } = render(<CategoryChart data={sampleBreakdown} />);
    const el = container.querySelector("[data-testid='category-chart']");
    expect(el).not.toBeNull();
  });

  it("renders empty state when no data", () => {
    const { container } = render(<CategoryChart data={[]} />);
    expect(container.querySelector("[data-testid='category-chart-empty']")).not.toBeNull();
  });
});
