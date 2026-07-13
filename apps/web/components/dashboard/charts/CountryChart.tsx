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
  "#0ea5e9", "#6366f1", "#14b8a6", "#f97316", "#ec4899",
  "#8b5cf6", "#22c55e", "#eab308", "#ef4444", "#84cc16",
  "#06b6d4", "#a855f7",
];

function CountryTooltip({ active, payload }: { active?: boolean; payload?: Array<{ name: string; value: number }> }) {
  if (!active || !payload?.length) return null;
  const item = payload[0];
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-800">
      <p className="font-medium text-slate-900 dark:text-white">{item.name}</p>
      <p className="text-slate-600 dark:text-slate-400">{item.value.toLocaleString("es-CO")} convocatorias</p>
    </div>
  );
}

export function CountryChart({ data }: { data: DashboardBreakdownItem[] }) {
  const chartData = useMemo(() => {
    return [...data]
      .sort((a, b) => b.total - a.total)
      .slice(0, 12)
      .map((d) => ({
        name: d.name,
        value: d.total,
      }));
  }, [data]);

  const handleClick = useCallback((entry: { name: string }) => {
    console.debug("Country chart click:", entry.name);
  }, []);

  if (!data.length) {
    return (
      <div
        className="flex h-[320px] items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/30"
        data-testid="country-chart-empty"
      >
        Sin distribución geográfica todavía
      </div>
    );
  }

  return (
    <div data-testid="country-chart" style={{ width: "100%", height: 300, position: "relative" }}>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 20, bottom: 20, left: 20, right: 40 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: 11, fill: "#64748b" }}
            width={120}
          />
          <Tooltip content={<CountryTooltip />} cursor={{ fill: "#f1f5f9" }} />
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
