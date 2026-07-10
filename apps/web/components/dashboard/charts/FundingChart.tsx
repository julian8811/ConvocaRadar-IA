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

const COLORS = ["#0ea5e9", "#6366f1", "#14b8a6", "#f97316", "#ec4899"];

export function FundingChart({ data }: { data: DashboardBreakdownItem[] }) {
  const chartData = useMemo(() => {
    return data.map((d) => ({
      name: d.name,
      value: d.total,
    }));
  }, [data]);

  if (!data.length) {
    return (
      <div className="flex h-[250px] items-center justify-center text-sm text-slate-500" data-testid="funding-chart-empty">
        Sin datos de financiamiento
      </div>
    );
  }

  return (
    <div data-testid="funding-chart" style={{ width: "100%", height: 250, position: "relative" }}>
      <ResponsiveContainer width="100%" height={250}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 10, bottom: 10, left: 100, right: 30 }}
        >
          <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: 11, fill: "#64748b" }}
            width={90}
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
