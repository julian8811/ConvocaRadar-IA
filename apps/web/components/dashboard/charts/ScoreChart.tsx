"use client";

import { useMemo, useCallback } from "react";
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Cell, Tooltip, CartesianGrid } from "recharts";
import type { DashboardBreakdownItem } from "@/lib/types";

const COLORS = ["#ef4444", "#f59e0b", "#06b6d4", "#16a34a"];

function ScoreTooltip({ active, payload }: { active?: boolean; payload?: Array<{ name: string; value: number }> }) {
  if (!active || !payload?.length) return null;
  const item = payload[0];
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-800">
      <p className="font-medium text-slate-900 dark:text-white">Score: {item.name}</p>
      <p className="text-slate-600 dark:text-slate-400">{item.value.toLocaleString("es-CO")} convocatorias</p>
    </div>
  );
}

export function ScoreChart({ data }: { data: DashboardBreakdownItem[] }) {
  const chartData = useMemo(() => {
    return [...data]
      .sort((a, b) => parseInt(a.name) - parseInt(b.name))
      .map((d) => ({
        name: d.name,
        value: d.total,
      }));
  }, [data]);

  const handleClick = useCallback((entry: { name: string }) => {
    console.debug("Score chart click:", entry.name);
  }, []);

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
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ fontSize: 11, fill: "#64748b" }}
            label={{ value: "Score range", position: "bottom", fontSize: 11, fill: "#64748b" }}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#64748b" }}
            label={{ value: "Count", angle: -90, position: "insideLeft", fontSize: 11, fill: "#64748b" }}
          />
          <Tooltip content={<ScoreTooltip />} cursor={{ fill: "#f1f5f9" }} />
          <Bar
            dataKey="value"
            radius={[4, 4, 0, 0]}
            isAnimationActive={true}
            animationDuration={600}
            cursor="pointer"
            onClick={(entry: unknown) => handleClick(entry as { name: string })}
          >
            {chartData.map((_, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
