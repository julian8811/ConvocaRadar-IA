"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
} from "recharts";
import type { DashboardBreakdownItem } from "@/lib/types";

export function SourceChart({ data }: { data: DashboardBreakdownItem[] }) {
  const chartData = useMemo(() => {
    return [...data]
      .sort((a, b) => b.total - a.total)
      .slice(0, 10)
      .map((d) => ({
        name: d.name.length > 30 ? d.name.slice(0, 30) + "..." : d.name,
        value: d.total,
      }));
  }, [data]);

  if (!data.length) {
    return (
      <div className="flex h-[250px] items-center justify-center text-sm text-slate-500" data-testid="source-chart-empty">
        Sin datos de fuentes
      </div>
    );
  }

  return (
    <div data-testid="source-chart" style={{ width: "100%", height: Math.max(250, chartData.length * 28), position: "relative" }}>
      <ResponsiveContainer width="100%" height={Math.max(250, chartData.length * 28)}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 10, bottom: 10, left: 180, right: 30 }}
        >
          <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: 10, fill: "#64748b" }}
            width={170}
          />
          <Bar dataKey="value" fill="#06b6d4" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
