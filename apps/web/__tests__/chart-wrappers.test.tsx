/**
 * REQ-FE-CHARTS-1 — Code-split wrapper smoke tests (PR3).
 *
 * Each dashboard chart file is a thin next/dynamic ssr:false wrapper around
 * a lazily-loaded *ChartClient module. These tests pin the split contract
 * per wrapper:
 *
 * 1. The client chunk is NOT part of the first synchronous paint (lazy
 *    boundary is real — guards against accidental re-inlining of Recharts).
 * 2. After the async chunk loads, the real chart content renders with data.
 * 3. Empty-state props pass through the async boundary unchanged.
 *
 * Rendering happens in happy-dom (client-like environment); any SSR-time
 * crash ("window is not defined" etc.) would surface here as an import or
 * render failure.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import StatusChartWrapper from "@/components/dashboard/charts/StatusChart";
import CountryChartWrapper from "@/components/dashboard/charts/CountryChart";
import ScoreChartWrapper from "@/components/dashboard/charts/ScoreChart";
import FundingChartWrapper from "@/components/dashboard/charts/FundingChart";
import SourceChartWrapper from "@/components/dashboard/charts/SourceChart";
import CategoryChartWrapper from "@/components/dashboard/charts/CategoryChart";

const sampleBreakdown = [
  { name: "Abierta", total: 45 },
  { name: "Cerrada", total: 30 },
];

afterEach(() => {
  cleanup();
});

interface WrapperCase {
  name: string;
  Wrapper: React.ComponentType<{ data: { name: string; total: number }[] }>;
  loadedTestId: string;
  emptyTestId: string;
  emptyMessage: string;
}

const cases: WrapperCase[] = [
  { name: "StatusChart", Wrapper: StatusChartWrapper, loadedTestId: "status-chart", emptyTestId: "status-chart-empty", emptyMessage: "Sin convocatorías" },
  { name: "CountryChart", Wrapper: CountryChartWrapper, loadedTestId: "country-chart", emptyTestId: "country-chart-empty", emptyMessage: "Sin distribución geográfica" },
  { name: "ScoreChart", Wrapper: ScoreChartWrapper, loadedTestId: "score-chart", emptyTestId: "score-chart-empty", emptyMessage: "Sin scores calculados" },
  { name: "FundingChart", Wrapper: FundingChartWrapper, loadedTestId: "funding-chart", emptyTestId: "funding-chart-empty", emptyMessage: "Sin datos de financiamiento" },
  { name: "SourceChart", Wrapper: SourceChartWrapper, loadedTestId: "source-chart", emptyTestId: "source-chart-empty", emptyMessage: "Sin datos de fuentes" },
  { name: "CategoryChart", Wrapper: CategoryChartWrapper, loadedTestId: "category-chart", emptyTestId: "category-chart-empty", emptyMessage: "Sin datos de categorías" },
];

describe.each(cases)("$name ssr:false wrapper", ({ name, Wrapper, loadedTestId, emptyTestId, emptyMessage }) => {
  it(`lazily loads: no ${loadedTestId} on first sync paint, present after chunk load`, async () => {
    const { container } = render(<Wrapper data={sampleBreakdown} />);

    // The dynamic boundary has not resolved within the synchronous act() of
    // render() — if this ever becomes non-null, Recharts got re-inlined.
    expect(container.querySelector(`[data-testid='${loadedTestId}']`)).toBeNull();

    const el = await screen.findByTestId(loadedTestId);
    expect(el).not.toBeNull();
  });

  it("renders real content after load and passes empty state through the boundary", async () => {
    render(<Wrapper data={sampleBreakdown} />);
    expect(await screen.findByTestId(loadedTestId)).not.toBeNull();

    cleanup();
    render(<Wrapper data={[]} />);
    const empty = await screen.findByTestId(emptyTestId);
    expect(empty.textContent).toContain(emptyMessage);
  });
});
