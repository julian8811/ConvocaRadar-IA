"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";
import type { DashboardBreakdownItem } from "@/lib/types";

// Plotly is a heavy library (~3.6 MB). Dynamic import with ssr: false
// so it only loads on the client and never blocks the server render.
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

const COLORS = ["#16a34a", "#f59e0b", "#64748b", "#ef4444", "#94a3b8", "#06b6d4"];

export function PlotlyStatusChart({ data }: { data: DashboardBreakdownItem[] }) {
  const { values, labels, percentages, total } = useMemo(() => {
    const sorted = [...data].sort((a, b) => b.total - a.total);
    const total = sorted.reduce((s, i) => s + i.total, 0);
    return {
      values: sorted.map((d) => d.total),
      labels: sorted.map((d) => d.name),
      percentages: sorted.map((d) =>
        total > 0 ? ((d.total / total) * 100).toFixed(1) + "%" : "0%",
      ),
      total,
    };
  }, [data]);

  if (!data.length) {
    return (
      <div className="flex h-[320px] items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/30">
        Sin convocatorias todavía
      </div>
    );
  }

  return (
    <Plot
      data={[
        {
          type: "pie" as const,
          labels,
          values,
          hole: 0.45,
          text: labels.map((l, i) => `${l}: ${values[i]} (${percentages[i]})`),
          textinfo: "label+percent",
          textposition: "outside",
          marker: {
            colors: COLORS.slice(0, labels.length),
            line: { color: "white", width: 2 },
          },
          hoverinfo: "label+value+percent",
          hovertemplate: "<b>%{label}</b><br>%{value} convocatorias (%{percent})<extra></extra>",
        },
      ]}
      layout={{
        height: 300,
        margin: { t: 20, b: 20, l: 20, r: 20 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: { family: "Inter, sans-serif", size: 11, color: "#64748b" },
        showlegend: false,
        annotations: [
          {
            text: `<b>${total}</b><br>total`,
            showarrow: false,
            font: { size: 16, color: "#1e293b" },
            x: 0.5,
            y: 0.5,
          },
        ],
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
