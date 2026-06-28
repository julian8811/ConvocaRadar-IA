"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";
import type { DashboardBreakdownItem } from "@/lib/types";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

const COLORS = [
  "#0ea5e9", "#6366f1", "#14b8a6", "#f97316", "#ec4899",
  "#8b5cf6", "#22c55e", "#eab308", "#ef4444", "#84cc16",
  "#06b6d4", "#a855f7", "#f43f5e", "#10b981",
];

export function PlotlyCountryChart({ data }: { data: DashboardBreakdownItem[] }) {
  const { countries, values, total } = useMemo(() => {
    const sorted = [...data].sort((a, b) => b.total - a.total).slice(0, 12);
    return {
      countries: sorted.map((d) => d.name),
      values: sorted.map((d) => d.total),
      total: sorted.reduce((s, i) => s + i.total, 0),
    };
  }, [data]);

  if (!data.length) {
    return (
      <div className="flex h-[320px] items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/30">
        Sin distribución geográfica todavía
      </div>
    );
  }

  return (
    <Plot
      data={[
        {
          type: "bar" as const,
          x: values,
          y: countries,
          orientation: "h",
          text: values.map((v) => `${v} (${total > 0 ? ((v / total) * 100).toFixed(0) : 0}%)`),
          textposition: "auto" as const,
          marker: {
            color: values.map((_, i) => COLORS[i % COLORS.length]),
            line: { color: "white", width: 2 },
          },
          hoverinfo: "x+text",
          hovertemplate: "<b>%{y}</b><br>%{x} convocatorias<extra></extra>",
        },
      ]}
      layout={{
        height: 300,
        margin: { t: 20, b: 20, l: 120, r: 40 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: { family: "Inter, sans-serif", size: 11, color: "#64748b" },
        xaxis: { title: "Convocatorias", showgrid: true, gridcolor: "#e2e8f0", zeroline: false },
        yaxis: { automargin: true, showgrid: false },
      }}
      config={{
        displayModeBar: false,
        responsive: true,
      }}
      className="w-full"
      useResizeHandler
    />
  );
}
