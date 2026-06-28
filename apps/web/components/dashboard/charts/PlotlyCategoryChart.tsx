"use client";
import { useMemo } from "react";
import dynamic from "next/dynamic";
import type { DashboardBreakdownItem } from "@/lib/types";
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });
const COLORS = ["#16a34a","#f59e0b","#0ea5e9","#6366f1","#ec4899","#f97316","#14b8a6","#8b5cf6"];

export function PlotlyCategoryChart({ data }: { data: DashboardBreakdownItem[] }) {
  const { labels, values } = useMemo(() => {
    const sorted = [...data].sort((a,b) => b.total - a.total);
    return { labels: sorted.map(d => d.name.charAt(0).toUpperCase() + d.name.slice(1)), values: sorted.map(d => d.total) };
  }, [data]);
  if (!data.length) return <div className="flex h-[250px] items-center justify-center text-sm text-slate-500">Sin datos de categorías</div>;
  return (
    <Plot data={[{ type: "bar" as const, x: values, y: labels, orientation: "h", marker: { color: COLORS.slice(0,labels.length) }, text: values.map(v => `${v} convocatorias`), textposition: "auto" as const, hoverinfo: "x+text" }]}
      layout={{ height: Math.max(250, labels.length * 30), margin: { t:10,b:10,l:140,r:30 }, paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: { family: "Inter, sans-serif", size:11, color:"#64748b" }, xaxis: { title: "Convocatorias" } }}
      config={{ displayModeBar: false, responsive: true }} className="w-full" useResizeHandler />
  );
}
