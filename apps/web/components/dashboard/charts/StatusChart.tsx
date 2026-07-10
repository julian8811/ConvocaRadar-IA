"use client";

import { useMemo } from "react";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
} from "recharts";
import type { DashboardBreakdownItem } from "@/lib/types";

const COLORS = ["#16a34a", "#f59e0b", "#64748b", "#ef4444", "#94a3b8", "#06b6d4"];

export function StatusChart({ data }: { data: DashboardBreakdownItem[] }) {
  const { chartData, total } = useMemo(() => {
    const sorted = [...data].sort((a, b) => b.total - a.total);
    const total = sorted.reduce((s, i) => s + i.total, 0);
    return { chartData: sorted, total };
  }, [data]);

  if (!data.length) {
    return (
      <div
        className="flex h-[320px] items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/30"
        data-testid="status-chart-empty"
      >
        Sin convocatorías todavía
      </div>
    );
  }

  return (
    <div data-testid="status-chart" style={{ width: "100%", height: 300, position: "relative" }}>
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie
            data={chartData}
            dataKey="total"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={75}
            outerRadius={110}
            paddingAngle={2}
          >
            {chartData.map((_, index) => (
              <Cell
                key={`cell-${index}`}
                fill={COLORS[index % COLORS.length]}
                stroke="white"
                strokeWidth={2}
              />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
