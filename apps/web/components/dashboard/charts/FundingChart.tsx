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

const COLORS = ["#0ea5e9", "#6366f1", "#14b8a6", "#f97316", "#ec4899"];

function FundingTooltip({ active, payload }: { active?: boolean; payload?: Array<{ name: string; value: number }> }) {
  if (!active || !payload?.length) return null;
  const item = payload[0];
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-800">
      <p className="font-medium text-slate-900 dark:text-white">{item.name}</p>
      <p className="text-slate-600 dark:text-slate-400">{item.value.toLocaleString("es-CO")} convocatorias</p>
    </div>
  );
}

export function FundingChart({ data }: { data: DashboardBreakdownItem[] }) {
  const chartData = useMemo(() => {
    return data.map((d) => ({
      name: d.name,
      value: d.total,
    }));
  }, [data]);

  const handleClick = useCallback((entry: { name: string }) => {
    console.debug("Funding chart click:", entry.name);
  }, []);

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
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: 11, fill: "#64748b" }}
            width={90}
          />
          <Tooltip content={<FundingTooltip />} cursor={{ fill: "#f1f5f9" }} />
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
