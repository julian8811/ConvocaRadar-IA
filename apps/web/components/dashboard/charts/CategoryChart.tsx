"use client";

import { useMemo, useCallback } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Cell,
  Tooltip,
  CartesianGrid,
} from "recharts";
import type { DashboardBreakdownItem } from "@/lib/types";

const COLORS = [
  "#16a34a", "#f59e0b", "#0ea5e9", "#6366f1", "#ec4899",
  "#f97316", "#14b8a6", "#8b5cf6",
];

function CategoryTooltip({ active, payload }: { active?: boolean; payload?: Array<{ name: string; value: number }> }) {
  if (!active || !payload?.length) return null;
  const item = payload[0];
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-800">
      <p className="font-medium text-slate-900 dark:text-white">{item.name}</p>
      <p className="text-slate-600 dark:text-slate-400">{item.value.toLocaleString("es-CO")} convocatorias</p>
    </div>
  );
}

export function CategoryChart({ data }: { data: DashboardBreakdownItem[] }) {
  const chartData = useMemo(() => {
    return [...data]
      .sort((a, b) => b.total - a.total)
      .map((d) => ({
        name: d.name.charAt(0).toUpperCase() + d.name.slice(1),
        value: d.total,
      }));
  }, [data]);

  const handleClick = useCallback((entry: { name: string }) => {
    console.debug("Category chart click:", entry.name);
  }, []);

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
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: 11, fill: "#64748b" }}
            width={130}
          />
          <Tooltip content={<CategoryTooltip />} cursor={{ fill: "#f1f5f9" }} />
          <Bar
            dataKey="value"
            radius={[0, 4, 4, 0]}
            isAnimationActive={true}
            animationDuration={600}
            cursor="pointer"
            onClick={(entry: unknown) => handleClick(entry as { name: string })}
          >
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
