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
import { AlertTriangle, Database, MapPinned, TrendingUp } from "lucide-react";
import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { DashboardDataCoverage, HealthRead, SourceHealth } from "@/lib/types";
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
  { border: "border-t-cyan-500", icon: "M3 3h18v18H3z" },
  { border: "border-t-emerald-500", icon: "M5 12h14" },
  { border: "border-t-amber-500", icon: "M12 8v8" },
  { border: "border-t-violet-500", icon: "M12 3v18" },
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
        <Card key={item.label} className={`border-t-4 ${item.accent.border} transition-all hover:shadow-lg`}>
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

export function HealthZone() {
  const query = useQuery<HealthRead>({
    queryKey: ["dashboard-health"],
    queryFn: api.dashboardHealth,
    placeholderData: keepPreviousData,
  });

  if (query.isLoading) return <HealthSkeleton />;
  if (query.error) return <ErrorState message={query.error.message} />;
  if (!query.data) return null;

  const data = query.data;

  return (
    <div className="space-y-4" data-zone="health">
      <SourceHealthBanner
        degraded={data.degraded_sources}
        failing={data.failing_sources}
        sourceAlerts={data.source_alerts}
      />
      <KpiCards kpis={data.kpis} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <TrendingUp className="h-4 w-4" />
              Estado de convocatorias
            </CardTitle>
            <CardDescription>Distribución agregada en servidor, sin muestreo parcial.</CardDescription>
          </CardHeader>
          <CardContent className="pt-5">
            <StatusChart data={data.status_breakdown} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <MapPinned className="h-4 w-4" />
              Convocatorias por país
            </CardTitle>
            <CardDescription>Top países con mayor volumen detectado.</CardDescription>
          </CardHeader>
          <CardContent className="pt-5">
            <CountryChart data={data.country_breakdown} />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <TrendingUp className="h-4 w-4" />
              Distribución de scores
            </CardTitle>
            <CardDescription>Cuántas convocatorias en cada rango de compatibilidad.</CardDescription>
          </CardHeader>
          <CardContent className="pt-5">
            <ScoreChart data={data.score_distribution} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <TrendingUp className="h-4 w-4" />
              Rangos de financiamiento
            </CardTitle>
            <CardDescription>Distribución por monto de financiamiento.</CardDescription>
          </CardHeader>
          <CardContent className="pt-5">
            <FundingChart data={data.funding_ranges} />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-1">
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Database className="h-4 w-4" />
              Contribución por fuente
            </CardTitle>
            <CardDescription>Top fuentes que más convocatorias aportan.</CardDescription>
          </CardHeader>
          <CardContent className="pt-5">
            <SourceChart data={data.source_contribution} />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <TrendingUp className="h-4 w-4" />
              Categorías de convocatorias
            </CardTitle>
            <CardDescription>Distribución por tipo: innovación, investigación, emprendimiento, etc.</CardDescription>
          </CardHeader>
          <CardContent className="pt-5">
            <CategoryChart data={data.category_distribution} />
          </CardContent>
        </Card>
      </div>

      <DataCoverageStrip dataCoverage={data.data_coverage} />
      {/* Suppress unused-import warnings for types we re-export indirectly. */}
      <span className="hidden" data-source-health-count={(data.sources_health as SourceHealth[]).length} />
    </div>
  );
}
