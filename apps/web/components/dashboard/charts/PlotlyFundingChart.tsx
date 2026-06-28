"use client";
import { useMemo } from "react";
import dynamic from "next/dynamic";
import type { DashboardBreakdownItem } from "@/lib/types";
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });
const COLORS = ["#0ea5e9", "#6366f1", "#14b8a6", "#f97316", "#ec4899"];

export function PlotlyFundingChart({ data }: { data: DashboardBreakdownItem[] }) {
  const { labels, values } = useMemo(() => ({ labels: data.map((d) => d.name), values: data.map((d) => d.total) }), [data]);
  if (!data.length) return <div className="flex h-[250px] items-center justify-center text-sm text-slate-500">Sin datos de financiamiento</div>;
  return (
    <Plot data={[{ type: "bar" as const, x: values, y: labels, orientation: "h", marker: { color: COLORS.slice(0, labels.length) }, hoverinfo: "x+y" }]}
      layout={{ height: 250, margin: { t: 10, b: 10, l: 100, r: 30 }, paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: { family: "Inter, sans-serif", size: 11, color: "#64748b" }, xaxis: { title: "Count" } }}
      config={{ displayModeBar: false, responsive: true }} className="w-full" useResizeHandler />
  );
}
