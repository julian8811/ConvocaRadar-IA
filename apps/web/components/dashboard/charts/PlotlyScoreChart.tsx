"use client";
import { useMemo } from "react";
import dynamic from "next/dynamic";
import type { DashboardBreakdownItem } from "@/lib/types";
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });
const COLORS = ["#ef4444", "#f59e0b", "#06b6d4", "#16a34a"];

export function PlotlyScoreChart({ data }: { data: DashboardBreakdownItem[] }) {
  const { labels, values } = useMemo(() => {
    const sorted = [...data].sort((a, b) => parseInt(a.name) - parseInt(b.name));
    return { labels: sorted.map((d) => d.name), values: sorted.map((d) => d.total) };
  }, [data]);
  if (!data.length) return <div className="flex h-[250px] items-center justify-center text-sm text-slate-500">Sin scores calculados</div>;
  return (
    <Plot data={[{ type: "bar" as const, x: labels, y: values, marker: { color: COLORS.slice(0, labels.length) }, text: values.map((v) => `${v} convocatorias`), textposition: "auto" as const, hoverinfo: "x+y+text" }]}
      layout={{ height: 250, margin: { t: 10, b: 40, l: 40, r: 10 }, paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: { family: "Inter, sans-serif", size: 11, color: "#64748b" }, xaxis: { title: "Score range" }, yaxis: { title: "Count" } }}
      config={{ displayModeBar: false, responsive: true }} className="w-full" useResizeHandler />
  );
}
