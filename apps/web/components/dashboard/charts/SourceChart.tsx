"use client";

import { useMemo, useCallback } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import type { DashboardBreakdownItem } from "@/lib/types";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function SourceTooltip({ active, payload }: { active?: boolean; payload?: any[] }) {
  if (!active || !payload?.length) return null;
  const item = payload[0];
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-800">
      <p className="font-medium text-slate-900 dark:text-white">{item.payload.fullName}</p>
      <p className="text-slate-600 dark:text-slate-400">{Number(item.value).toLocaleString("es-CO")} convocatorias</p>
    </div>
  );
}

export function SourceChart({ data }: { data: DashboardBreakdownItem[] }) {
  const chartData = useMemo(() => {
    return [...data]
      .sort((a, b) => b.total - a.total)
      .slice(0, 10)
      .map((d) => ({
        name: d.name.length > 30 ? d.name.slice(0, 30) + "..." : d.name,
        fullName: d.name,
        value: d.total,
      }));
  }, [data]);

  const handleClick = useCallback((entry: { fullName: string }) => {
    console.debug("Source chart click:", entry.fullName);
  }, []);

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
          <Tooltip content={<SourceTooltip />} cursor={{ fill: "#f1f5f9" }} />
          <Bar
            dataKey="value"
            fill="#06b6d4"
            radius={[0, 4, 4, 0]}
            isAnimationActive={true}
            animationDuration={600}
            cursor="pointer"
            onClick={(entry: unknown) => handleClick(entry as { fullName: string })}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
