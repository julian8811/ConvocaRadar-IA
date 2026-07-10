"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { DashboardBreakdownItem } from "@/lib/types";

const COLORS = [
  "#16a34a", "#f59e0b", "#0ea5e9", "#6366f1", "#ec4899",
  "#f97316", "#14b8a6", "#8b5cf6",
];

export function CategoryChart({ data }: { data: DashboardBreakdownItem[] }) {
  const chartData = useMemo(() => {
    return [...data]
      .sort((a, b) => b.total - a.total)
      .map((d) => ({
        name: d.name.charAt(0).toUpperCase() + d.name.slice(1),
        value: d.total,
      }));
  }, [data]);

  if (!data.length) {
    return (
      <div className="flex h-[250px] items-center justify-center text-sm text-slate-500" data-testid="category-chart-empty">
        Sin datos de categorías
      </div>
    );
  }

  return (
    <div data-testid="category-chart" style={{ width: "100%", height: Math.max(250, chartData.length * 30), position: "relative" }}>
      <ResponsiveContainer width="100%" height={Math.max(250, chartData.length * 30)}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 10, bottom: 10, left: 140, right: 30 }}
        >
          <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: 11, fill: "#64748b" }}
            width={130}
          />
          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
            {chartData.map((_, index) => (
              <Cell
                key={`cell-${index}`}
                fill={COLORS[index % COLORS.length]}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
