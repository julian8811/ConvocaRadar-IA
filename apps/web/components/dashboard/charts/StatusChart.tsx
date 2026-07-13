"use client";

import { useMemo } from "react";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  Legend,
} from "recharts";
import type { DashboardBreakdownItem } from "@/lib/types";

const COLORS = ["#16a34a", "#f59e0b", "#64748b", "#ef4444", "#94a3b8", "#06b6d4"];

function StatusTooltip({ active, payload }: { active?: boolean; payload?: Array<{ name: string; value: number }> }) {
  if (!active || !payload?.length) return null;
  const item = payload[0];
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-800">
      <p className="font-medium text-slate-900 dark:text-white">{item.name}</p>
      <p className="text-slate-600 dark:text-slate-400">{item.value.toLocaleString("es-CO")} convocatorias</p>
    </div>
  );
}

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
            innerRadius={60}
            outerRadius={110}
            paddingAngle={2}
            isAnimationActive={true}
            animationDuration={600}
            cursor="pointer"
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
          <Tooltip content={<StatusTooltip />} />
          <Legend
            verticalAlign="bottom"
            height={36}
            formatter={(value: string) => (
              <span className="text-xs text-slate-700 dark:text-slate-300">{value}</span>
            )}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
