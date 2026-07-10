"use client";

import { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Cell } from "recharts";
import type { DashboardBreakdownItem } from "@/lib/types";

const COLORS = ["#ef4444", "#f59e0b", "#06b6d4", "#16a34a"];

export function ScoreChart({ data }: { data: DashboardBreakdownItem[] }) {
  const chartData = useMemo(() => {
    return [...data]
      .sort((a, b) => parseInt(a.name) - parseInt(b.name))
      .map((d) => ({
        name: d.name,
        value: d.total,
      }));
  }, [data]);

  if (!data.length) {
    return (
      <div className="flex h-[250px] items-center justify-center text-sm text-slate-500" data-testid="score-chart-empty">
        Sin scores calculados
      </div>
    );
  }

  return (
    <div data-testid="score-chart" style={{ width: "100%", height: 250, position: "relative" }}>
      <ResponsiveContainer width="100%" height={250}>
        <BarChart data={chartData} margin={{ top: 10, bottom: 40, left: 40, right: 10 }}>
          <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#64748b" }} label={{ value: "Score range", position: "bottom", fontSize: 11, fill: "#64748b" }} />
          <YAxis tick={{ fontSize: 11, fill: "#64748b" }} label={{ value: "Count", angle: -90, position: "insideLeft", fontSize: 11, fill: "#64748b" }} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {chartData.map((_, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
