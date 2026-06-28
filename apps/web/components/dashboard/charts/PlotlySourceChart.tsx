"use client";
import { useMemo } from "react";
import dynamic from "next/dynamic";
import type { DashboardBreakdownItem } from "@/lib/types";
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

export function PlotlySourceChart({ data }: { data: DashboardBreakdownItem[] }) {
  const { labels, values } = useMemo(() => {
    const sorted = [...data].sort((a, b) => b.total - a.total).slice(0, 10);
    return { labels: sorted.map((d) => d.name.length > 30 ? d.name.slice(0, 30) + "..." : d.name), values: sorted.map((d) => d.total) };
  }, [data]);
  if (!data.length) return <div className="flex h-[250px] items-center justify-center text-sm text-slate-500">Sin datos de fuentes</div>;
  return (
    <Plot data={[{ type: "bar" as const, x: values, y: labels, orientation: "h", marker: { color: values.map(() => "#06b6d4") }, hoverinfo: "x+y" }]}
      layout={{ height: Math.max(250, labels.length * 25), margin: { t: 10, b: 10, l: 180, r: 30 }, paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: { family: "Inter, sans-serif", size: 10, color: "#64748b" }, xaxis: { title: "Opportunities" } }}
      config={{ displayModeBar: false, responsive: true }} className="w-full" useResizeHandler />
  );
}
