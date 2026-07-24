/**
 * PR B-2 (dashboard-redesign): Health zone — sources + data quality.
 *
 * Renders:
 *   1. Source health banner (degraded + failing alerts)
 *   2. 4 KPI cards in a row (Total / Abiertas / Cierran pronto / Alta compatibilidad)
 *   3. Status breakdown donut chart (Plotly interactive)
 *   4. Country breakdown horizontal bar chart (Plotly interactive)
 *   5. Data coverage strip — 5 mini-stats, with "Sin datos aún" UX for null embeddings
 *
 * All charts are rendered client-side with Plotly via dynamic import
 * (SSR-safe, ~3.6 MB bundle loaded on-demand). Hover, click, and zoom
 * are interactive out of the box.
 */
"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Activity, AlertTriangle, Database, TrendingUp } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { DashboardDataCoverage, HealthRead, SourceHealth } from "@/lib/types";
import { cn } from "@/lib/utils";
import { HealthSkeleton } from "@/components/dashboard/skeletons/HealthSkeleton";
import {
  StatusChart,
  CountryChart,
  ScoreChart,
  FundingChart,
  SourceChart,
  CategoryChart,
} from "@/components/dashboard/charts";

function formatNumber(value: number) {
  return new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 }).format(value);
}

function SourceHealthBanner({ degraded, failing, sourceAlerts }: {
  degraded: number;
  failing: number;
  sourceAlerts: HealthRead["source_alerts"];
}) {
  const total = degraded + failing;
  if (total === 0) return null;
  return (
    <Card className="border-amber-500/30 bg-amber-500/5">
      <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-600 dark:text-amber-300" />
          <div>
            <p className="text-sm font-medium text-slate-950 dark:text-white">
              {total} fuente{total === 1 ? "" : "s"} requiere{total === 1 ? "" : "n"} atención
            </p>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
              {sourceAlerts.map((item) => item.name).join(", ") || "Revisa el estado operativo de tus conectores."}
            </p>
          </div>
        </div>
        <Link
          href="/sources"
          className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-4 text-sm font-medium text-slate-900 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800"
        >
          Ver fuentes
        </Link>
      </CardContent>
    </Card>
  );
}

const KPI_ACCENTS = [
  { border: "border-t-[#005652]", icon: "M3 3h18v18H3z" },
  { border: "border-t-[#00a6a1]", icon: "M5 12h14" },
  { border: "border-t-[#bed630]", icon: "M12 8v8" },
  { border: "border-t-[#6f7f1f]", icon: "M12 3v18" },
];

function KpiCards({ kpis }: { kpis: HealthRead["kpis"] }) {
  const items = [
    { label: "Total convocatorias", value: kpis.total, accent: KPI_ACCENTS[0] },
    { label: "Convocatorias abiertas", value: kpis.open, accent: KPI_ACCENTS[1] },
    { label: "Cierran pronto", value: kpis.closing_soon, accent: KPI_ACCENTS[2] },
    { label: "Alta compatibilidad", value: kpis.high_match, accent: KPI_ACCENTS[3] },
  ];
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <Card key={item.label} className={`rounded-2xl border-t-4 ${item.accent.border} transition-all hover:-translate-y-0.5 hover:shadow-lg`}>
          <CardContent className="p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{item.label}</p>
            <p className="mt-1 text-3xl font-bold text-slate-950 dark:text-white">{formatNumber(item.value)}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}



function DataCoverageStrip({ dataCoverage }: { dataCoverage: DashboardDataCoverage }) {
  const cells = [
    { label: "Con resumen", value: formatNumber(dataCoverage.with_summary) },
    { label: "Con monto", value: formatNumber(dataCoverage.with_amount) },
    { label: "Con fecha cierre", value: formatNumber(dataCoverage.with_close_date) },
    { label: "Con fuente", value: formatNumber(dataCoverage.with_source) },
  ];
  return (
    <Card>
      <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
        <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
          <Database className="h-4 w-4" />
          Calidad de datos
        </CardTitle>
        <CardDescription>Cobertura agregada de campos útiles para alertas y scoring.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 pt-5 sm:grid-cols-2 xl:grid-cols-5">
        {cells.map((c) => (
          <div key={c.label} className="rounded-md border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{c.label}</p>
            <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">{c.value}</p>
          </div>
        ))}
        <div className="rounded-md border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">Cobertura embeddings</p>
          {dataCoverage.embeddings_coverage === null ? (
            <p className="mt-1 text-lg font-semibold text-slate-500 dark:text-slate-400">Sin datos aún</p>
          ) : (
            <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">
              {Math.round(dataCoverage.embeddings_coverage * 10) / 10}%
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function healthColor(score: number): string {
  if (score >= 90) return "bg-emerald-500";
  if (score >= 70) return "bg-amber-400";
  if (score >= 50) return "bg-orange-500";
  return "bg-red-500";
}

function healthLabel(status: string): string {
  const map: Record<string, string> = {
    healthy: "Saludable",
    stable: "Estable",
    degraded: "Degradada",
    critical: "Crítica",
  };
  return map[status] ?? status;
}

function SourceHealthTable({ sources }: { sources: SourceHealth[] }) {
  if (!sources.length) return null;
  const sorted = [...sources].sort((a, b) => (a.health_score ?? 0) - (b.health_score ?? 0)).slice(0, 8);
  return (
    <Card>
      <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
        <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
          <Activity className="h-4 w-4" />
          Salud de fuentes
        </CardTitle>
        <CardDescription>Las ocho fuentes con menor puntaje para priorizar acciones de mantenimiento.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {sorted.map((s) => (
            <div key={s.source_id} className="flex items-center gap-4 px-4 py-3 text-sm hover:bg-slate-50 dark:hover:bg-slate-900/50">
              <div className="flex h-8 w-8 items-center justify-center" title={`Score: ${s.health_score}`}>
                <div className={cn("h-2.5 w-2.5 rounded-full", healthColor(s.health_score))} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-slate-950 dark:text-white">{s.name}</p>
                <p className="truncate text-xs text-slate-500 dark:text-slate-400">{s.key}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold tabular-nums text-slate-700 dark:text-slate-300">{s.health_score}</span>
                <span className="hidden text-xs text-slate-400 sm:inline">{healthLabel(s.health_status)}</span>
                {s.tier && (
                  <Badge tone="muted" className="text-[10px] uppercase tracking-wider">
                    {s.tier === "strategic" ? "Estratégica" : s.tier === "complementary" ? "Complementaria" : "Experimental"}
                  </Badge>
                )}
                {s.auto_paused && (
                  <Badge tone="destructive" className="text-[10px]">Pausada</Badge>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="border-t border-slate-200 p-4 text-right dark:border-slate-800">
          <Link href="/sources" className="text-sm font-semibold text-[#006b66] hover:text-[#004945] dark:text-[#74ddd8]">
            Consultar todas las fuentes →
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

export function HealthZone() {
  const [activeChart, setActiveChart] = useState("status");
  const query = useQuery<HealthRead>({
    queryKey: ["dashboard-health"],
    queryFn: api.dashboardHealth,
    placeholderData: keepPreviousData,
  });

  if (query.isLoading) return <HealthSkeleton />;
  if (query.error) return <ErrorState message={query.error.message} />;
  if (!query.data) return null;

  const data = query.data;
  const chartOptions = [
    { id: "status", label: "Estado", title: "Estado de convocatorias", description: "Distribución general según vigencia.", content: <StatusChart data={data.status_breakdown} /> },
    { id: "country", label: "País", title: "Cobertura geográfica", description: "Países con mayor volumen detectado.", content: <CountryChart data={data.country_breakdown} /> },
    { id: "score", label: "Compatibilidad", title: "Distribución de compatibilidad", description: "Convocatorias agrupadas por rango de afinidad.", content: <ScoreChart data={data.score_distribution} /> },
    { id: "funding", label: "Financiación", title: "Rangos de financiación", description: "Distribución según monto reportado.", content: <FundingChart data={data.funding_ranges} /> },
    { id: "source", label: "Fuentes", title: "Contribución por fuente", description: "Conectores que más oportunidades aportan.", content: <SourceChart data={data.source_contribution} /> },
    { id: "category", label: "Categorías", title: "Áreas de oportunidad", description: "Distribución temática de las convocatorias.", content: <CategoryChart data={data.category_distribution} /> },
  ];
  const selectedChart = chartOptions.find((item) => item.id === activeChart) ?? chartOptions[0];

  return (
    <div className="space-y-4" data-zone="health">
      <SourceHealthBanner
        degraded={data.degraded_sources}
        failing={data.failing_sources}
        sourceAlerts={data.source_alerts}
      />
      <KpiCards kpis={data.kpis} />
      <Card className="overflow-hidden border-[#005652]/15 shadow-[0_20px_50px_-35px_rgba(0,86,82,.8)]">
        <CardHeader className="border-b border-[#005652]/10 bg-[#f4f9f8] pb-4 dark:border-white/10 dark:bg-[#005652]/10">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
                <TrendingUp className="h-5 w-5 text-[#008b86]" />
                Analítica del observatorio
              </CardTitle>
              <CardDescription>Selecciona una dimensión para explorar los datos consolidados.</CardDescription>
            </div>
            <div className="flex max-w-full gap-1 overflow-x-auto rounded-xl border border-[#005652]/10 bg-white p-1 dark:bg-slate-900" role="tablist" aria-label="Dimensión del gráfico">
              {chartOptions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  role="tab"
                  aria-selected={activeChart === option.id}
                  onClick={() => setActiveChart(option.id)}
                  className={cn("whitespace-nowrap rounded-lg px-3 py-2 text-xs font-semibold transition", activeChart === option.id ? "bg-[#005652] text-white shadow-sm" : "text-slate-600 hover:bg-[#e8f6f5] hover:text-[#005652] dark:text-slate-300 dark:hover:bg-white/5")}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-5 lg:p-7">
          <div className="mb-4">
            <h3 className="text-lg font-semibold text-slate-950 dark:text-white">{selectedChart.title}</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">{selectedChart.description}</p>
          </div>
          <div role="tabpanel" className="min-h-[280px]">{selectedChart.content}</div>
        </CardContent>
      </Card>

      <SourceHealthTable sources={data.sources_health as SourceHealth[]} />
      <DataCoverageStrip dataCoverage={data.data_coverage} />
    </div>
  );
}
