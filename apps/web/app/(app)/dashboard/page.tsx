"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  CalendarClock,
  FileText,
  MapPinned,
  Play,
  RefreshCcw,
  Radar,
  Search,
  Sparkles,
  Tags,
  TrendingUp,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { AdminMetrics, Opportunity, SourceHealth, SourceRunOverview } from "@/lib/types";

const Plot = dynamic(async () => (await import("react-plotly.js")).default, { ssr: false }) as any;
const plotConfig = { displayModeBar: true, displaylogo: false, responsive: true, scrollZoom: true };

type ThemeMode = "light" | "dark";

function useDashboardTheme() {
  const [theme, setTheme] = useState<ThemeMode>("light");

  useEffect(() => {
    const sync = () => setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
    sync();
    window.addEventListener("convocaradar-theme-change", sync as EventListener);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("convocaradar-theme-change", sync as EventListener);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return theme;
}

function countBy(values: string[]) {
  const map = new Map<string, number>();
  for (const value of values) {
    const key = value.trim() || "Sin dato";
    map.set(key, (map.get(key) ?? 0) + 1);
  }
  return [...map.entries()]
    .map(([name, total]) => ({ name, total }))
    .sort((a, b) => b.total - a.total);
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("es-CO", { maximumFractionDigits: 1 }).format(value);
}

function formatPercent(value: number) {
  return `${Math.round(value)}%`;
}

function formatDuration(seconds: number | null) {
  if (seconds === null || Number.isNaN(seconds)) return "Sin dato";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  return `${minutes} min ${remaining.toString().padStart(2, "0")} s`;
}

function formatDays(value: number | null) {
  if (value === null || Number.isNaN(value)) return "Sin dato";
  return `${value} d`;
}

function sourceName(item: Opportunity, health: SourceHealth[]) {
  return health.find((source) => source.source_id === item.source_id)?.name ?? "Fuente no identificada";
}

function formatAmount(item: Opportunity) {
  if (item.funding_amount_raw?.trim()) return item.funding_amount_raw;
  if (item.funding_amount_value === null) return "Por validar";
  const currency = item.funding_amount_currency ? ` ${item.funding_amount_currency}` : "";
  return `${formatNumber(item.funding_amount_value)}${currency}`;
}

function translateOpportunityStatus(status: string) {
  const map: Record<string, string> = {
    open: "Abierta",
    closing_soon: "Cierre próximo",
    closed: "Cerrada",
    unknown: "Sin fecha",
  };
  return map[status] ?? status;
}

function translateOperationalStatus(status: string) {
  const map: Record<string, string> = {
    failed: "Fallida",
    queued: "En cola",
    scheduled: "Programada",
    running: "En ejecución",
    success: "Exitosa",
    idle: "Inactiva",
    pending: "Pendiente",
    paused: "Pausada",
  };
  return map[status] ?? status;
}

function translateSourceHealthStatus(status: string) {
  const map: Record<string, string> = {
    healthy: "Sana",
    degraded: "Degradada",
    failing: "Fallando",
    idle: "Inactiva",
  };
  return map[status] ?? status;
}

function monthKey(value: string) {
  const date = new Date(`${value}-01T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-CO", { month: "short", year: "numeric" }).format(date);
}

function plotColors(theme: ThemeMode) {
  return {
    text: theme === "dark" ? "#dbeafe" : "#102033",
    muted: theme === "dark" ? "#a3b3c4" : "#526173",
    grid: theme === "dark" ? "rgba(148,163,184,0.16)" : "rgba(148,163,184,0.3)",
    paper: theme === "dark" ? "#0d1a29" : "#ffffff",
    plot: theme === "dark" ? "#0d1a29" : "#ffffff",
    title: theme === "dark" ? "#f8fafc" : "#102033",
  };
}

function buildBaseLayout(theme: ThemeMode, title: string, xTitle: string, yTitle: string, extra: Record<string, unknown> = {}) {
  const colors = plotColors(theme);
  return {
    autosize: true,
    height: 420,
    title: { text: title, font: { size: 15, color: colors.title } },
    paper_bgcolor: colors.paper,
    plot_bgcolor: colors.plot,
    margin: { l: 104, r: 40, t: 72, b: 120 },
    font: { color: colors.text, family: "Geist, sans-serif" },
    hovermode: "closest",
    showlegend: false,
    uniformtext: { mode: "hide", minsize: 10 },
    xaxis: {
      title: xTitle ? { text: xTitle, font: { color: colors.muted }, standoff: 24 } : undefined,
      tickfont: { color: colors.text },
      automargin: true,
      gridcolor: colors.grid,
      zeroline: false,
      ticks: "outside",
      ticklen: 6,
    },
    yaxis: {
      title: yTitle ? { text: yTitle, font: { color: colors.muted }, standoff: 24 } : undefined,
      tickfont: { color: colors.text },
      automargin: true,
      gridcolor: colors.grid,
      zeroline: false,
      ticks: "outside",
      ticklen: 6,
    },
    ...extra,
  };
}

export default function DashboardPage() {
  const theme = useDashboardTheme();
  const queryClient = useQueryClient();

  const opportunities = useQuery({ queryKey: ["opportunities"], queryFn: () => api.opportunities("page=1&page_size=100") });
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const sourceHealth = useQuery({ queryKey: ["source-health"], queryFn: api.sourceHealth });
  const adminMetrics = useQuery({ queryKey: ["admin-metrics"], queryFn: api.adminMetrics });
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  const sourceRunsOverview = useQuery({ queryKey: ["source-runs-overview"], queryFn: api.sourceRunsOverview });

  const createReport = useMutation({
    mutationFn: () => api.createReport({ title: "Reporte ejecutivo desde el tablero", format: "html" }),
    onSuccess: () => {
      toast.success("Reporte generado");
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo generar el reporte"),
  });

  const runCapture = useMutation({
    mutationFn: api.runAllSources,
    onSuccess: (resultRuns) => {
      const created = resultRuns.reduce((total, run) => total + run.items_created, 0);
      const found = resultRuns.reduce((total, run) => total + run.items_found, 0);
      toast.success(`Scraping finalizado: ${found} detectadas, ${created} nuevas`);
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      queryClient.invalidateQueries({ queryKey: ["sources"] });
      queryClient.invalidateQueries({ queryKey: ["source-health"] });
      queryClient.invalidateQueries({ queryKey: ["admin-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["source-runs-overview"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo ejecutar el scraping"),
  });

  const opportunityItems = useMemo(() => opportunities.data?.items ?? [], [opportunities.data?.items]);
  const sourceItems = useMemo(() => sources.data ?? [], [sources.data]);
  const healthItems = useMemo(() => sourceHealth.data ?? [], [sourceHealth.data]);
  const taskItems = useMemo(() => tasks.data ?? [], [tasks.data]);
  const runItems = useMemo(() => sourceRunsOverview.data ?? [], [sourceRunsOverview.data]);
  const metrics = adminMetrics.data as AdminMetrics | undefined;

  const total = opportunities.data?.total ?? opportunityItems.length;
  const loadedCount = opportunityItems.length;
  const open = opportunityItems.filter((item) => item.status === "open").length;
  const closingSoon = opportunityItems.filter((item) => item.status === "closing_soon").length;
  const recentOpportunityItems = opportunityItems.filter((item) => item.status !== "closed").slice(0, 6);
  const closed = opportunityItems.filter((item) => item.status === "closed").length;
  const unknown = opportunityItems.filter((item) => item.status === "unknown").length;
  const withSource = opportunityItems.filter((item) => item.source_id).length;
  const withAmount = opportunityItems.filter((item) => item.funding_amount_value !== null || item.funding_amount_raw).length;
  const withSummary = opportunityItems.filter((item) => item.summary.trim().length > 0).length;
  const withCategories = opportunityItems.filter((item) => item.categories.length > 0).length;
  const withDate = opportunityItems.filter((item) => item.close_date).length;

  const countries = useMemo(() => countBy(opportunityItems.map((item) => item.country)).slice(0, 8), [opportunityItems]);
  const categories = useMemo(
    () => countBy(opportunityItems.flatMap((item) => (item.categories.length ? item.categories : ["Sin categoría"]))).slice(0, 8),
    [opportunityItems],
  );
  const months = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of opportunityItems) {
      if (!item.close_date) continue;
      const key = item.close_date.slice(0, 7);
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return [...map.entries()]
      .map(([month, totalItems]) => ({ month: monthKey(month), total: totalItems }))
      .sort((a, b) => a.month.localeCompare(b.month, "es"));
  }, [opportunityItems]);

  const averageSuccessRate = healthItems.length ? healthItems.reduce((sum, item) => sum + item.success_rate, 0) / healthItems.length : 0;
  const averageFailureRate = healthItems.length ? healthItems.reduce((sum, item) => sum + item.failure_rate, 0) / healthItems.length : 0;
  const averageRunDuration = healthItems.length
    ? healthItems
        .filter((item) => item.last_run_duration_seconds !== null)
        .reduce((sum, item) => sum + (item.last_run_duration_seconds ?? 0), 0) /
      Math.max(healthItems.filter((item) => item.last_run_duration_seconds !== null).length, 1)
    : 0;
  const recentSuccessfulRuns = runItems.filter((run) => run.status === "success" || run.status === "degraded").length;
  const sourcesWithRuns = healthItems.filter((item) => item.recent_runs > 0).length;
  const topActiveSources = [...healthItems].sort((a, b) => b.recent_items_found - a.recent_items_found).slice(0, 5);

  const healthCounts = {
    healthy: healthItems.filter((item) => item.status === "healthy").length,
    degraded: healthItems.filter((item) => item.status === "degraded").length,
    failing: healthItems.filter((item) => item.status === "failing").length,
    idle: healthItems.filter((item) => item.status === "idle").length,
  };

  const attentionSources = healthItems
    .filter((item) => item.status !== "healthy")
    .sort((a, b) => {
      const statusWeight = { failing: 0, degraded: 1, idle: 2 } as Record<string, number>;
      return (statusWeight[a.status] ?? 3) - (statusWeight[b.status] ?? 3);
    });

  const barTheme = theme === "dark" ? "#22d3ee" : "#0ea5e9";
  const accentTheme = theme === "dark" ? "#38bdf8" : "#0284c7";
  const categoryTheme = theme === "dark" ? "#8b5cf6" : "#6366f1";
  const greenTheme = theme === "dark" ? "#22c55e" : "#16a34a";
  const redTheme = theme === "dark" ? "#ef4444" : "#dc2626";

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-cyan-700 dark:text-cyan-200">
            <Radar className="h-5 w-5" />
            <span className="text-xs font-medium uppercase tracking-[0.22em]">ConvocaRadar IA</span>
          </div>
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Panel principal</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
              Monitoreo centralizado de convocatorias, fuentes y calidad del scraping con una lectura clara en modo claro y oscuro.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => createReport.mutate()} disabled={createReport.isPending}>
            <FileText className="h-4 w-4" />
            {createReport.isPending ? "Generando..." : "Generar reporte"}
          </Button>
          <Button onClick={() => runCapture.mutate()} disabled={runCapture.isPending}>
            <Play className="h-4 w-4" />
            {runCapture.isPending ? "Capturando..." : "Capturar oportunidades"}
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total de convocatorias" value={total} detail="Convocatorias detectadas" />
        <StatCard label="Abiertas hoy" value={open} detail="Vigentes y listas para seguimiento" />
        <StatCard label="Cierre próximo" value={closingSoon} detail="Requieren atención" />
        <StatCard label="Con fuente asignada" value={withSource} detail="Trazabilidad completa" />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Con monto" value={withAmount} detail="Monto bruto o numérico" />
        <StatCard label="Con resumen IA" value={withSummary} detail="Texto sintetizado" />
        <StatCard label="Con categorías" value={withCategories} detail="Taxonomía aplicada" />
        <StatCard label="Con fecha de cierre" value={withDate} detail="Fecha utilizable para alertas" />
      </div>

      <div className="grid gap-4 xl:grid-cols-4">
        <StatCard label="Fuentes activas" value={metrics?.active_sources ?? sourceItems.filter((source) => source.enabled).length} detail="Disponibles para scraping" />
        <StatCard label="Cobertura embeddings" value={formatPercent(metrics?.embeddings_coverage ?? 0)} detail="Cobertura semántica" />
        <StatCard label="Alertas pendientes" value={metrics?.pending_alerts ?? 0} detail="Por enviar o revisar" />
        <StatCard label="Tareas fallidas" value={metrics?.failed_tasks ?? 0} detail="Procesos que requieren revisión" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Radar className="h-4 w-4" />
              Lectura operativa
            </CardTitle>
            <CardDescription>Resumen rápido del estado real del motor de captura y su ritmo reciente.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 pt-5 sm:grid-cols-2 xl:grid-cols-3">
            <InfoTile label="Fuentes con corrida" value={sourcesWithRuns} detail="Fuentes que ya produjeron actividad" />
            <InfoTile label="Corridas exitosas" value={recentSuccessfulRuns} detail="Ejecuciones completadas sin error" />
            <InfoTile label="Éxito promedio" value={formatPercent(averageSuccessRate)} detail="Promedio de salud reciente" />
            <InfoTile label="Fallo promedio" value={formatPercent(averageFailureRate)} detail="Tasa de error agregada" />
            <InfoTile label="Duración media" value={formatDuration(averageRunDuration)} detail="Tiempo medio de scraping" />
            <InfoTile label="Fuentes en atención" value={attentionSources.length} detail="Degradadas, fallando o inactivas" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Sparkles className="h-4 w-4" />
              Estado de la captura
            </CardTitle>
            <CardDescription>Si todavía no hay oportunidades visibles, esta sección explica dónde se está trabajando.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 pt-5 text-sm text-slate-700 dark:text-slate-300">
            {total > 0 ? (
              <>
                <p>Las convocatorias ya están entrando y el tablero muestra el volumen operativo en paralelo.</p>
                <p className="text-slate-500 dark:text-slate-400">
                  Cobertura actual: {formatPercent(loadedCount ? Math.round((withSummary / loadedCount) * 100) : 0)} de resúmenes,{" "}
                  {formatPercent(loadedCount ? Math.round((withDate / loadedCount) * 100) : 0)} de fechas y{" "}
                  {formatPercent(loadedCount ? Math.round((withSource / loadedCount) * 100) : 0)} de trazabilidad por fuente.
                </p>
              </>
            ) : (
              <>
                <p>No hay convocatorias visibles todavía en esta sesión.</p>
                <p className="text-slate-500 dark:text-slate-400">
                  El tablero sigue mostrando salud operativa real de fuentes, corridas y tareas, para que podamos ver dónde está creciendo la captura.
                </p>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <TrendingUp className="h-4 w-4" />
              Estado de las convocatorias
            </CardTitle>
            <CardDescription>Distribución entre abiertas, por cerrar, cerradas y sin validar.</CardDescription>
          </CardHeader>
          <CardContent className="relative h-[420px] pt-5">
            {total > 0 ? (
              <Plot
                config={plotConfig}
                useResizeHandler
                style={{ width: "100%", height: "100%" }}
                data={[
                  {
                    type: "bar",
                    orientation: "h",
                    y: ["Abierta", "Cierre próximo", "Cerrada", "Sin validar"],
                    x: [open, closingSoon, closed, unknown],
                    marker: { color: [greenTheme, "#f59e0b", redTheme, "#94a3b8"] },
                    hovertemplate: "%{y}<br>%{x} oportunidades<extra></extra>",
                  },
                ]}
                layout={buildBaseLayout(theme, "Estado de cierre", "Número de convocatorias", "Estado", {
                  margin: { l: 140, r: 24, t: 56, b: 56 },
                  xaxis: {
                    title: { text: "Número de convocatorias", font: { color: plotColors(theme).muted }, standoff: 18 },
                    tickfont: { color: plotColors(theme).text },
                    automargin: true,
                    gridcolor: plotColors(theme).grid,
                    zeroline: false,
                  },
                  yaxis: {
                    title: { text: "Estado", font: { color: plotColors(theme).muted }, standoff: 18 },
                    tickfont: { color: plotColors(theme).text },
                    automargin: true,
                    gridcolor: plotColors(theme).grid,
                    zeroline: false,
                  },
                })}
              />
            ) : (
              <ChartEmpty title="Sin oportunidades aún" detail="Cuando lleguen convocatorias, aquí verás su distribución por estado." />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <MapPinned className="h-4 w-4" />
              Distribución por país
            </CardTitle>
            <CardDescription>Lectura del volumen detectado por país de origen o cobertura.</CardDescription>
          </CardHeader>
          <CardContent className="relative h-[420px] pt-5">
            {countries.length > 0 ? (
              <Plot
                config={plotConfig}
                useResizeHandler
                style={{ width: "100%", height: "100%" }}
                data={[
                  {
                    type: "bar",
                    orientation: "h",
                    x: countries.map((item) => item.total),
                    y: countries.map((item) => item.name),
                    marker: { color: barTheme },
                    hovertemplate: "%{y}<br>%{x} convocatorias<extra></extra>",
                  },
                ]}
                layout={buildBaseLayout(theme, "Convocatorias por país", "Número de convocatorias", "País", {
                  margin: { l: 120, r: 24, t: 56, b: 56 },
                })}
              />
            ) : (
              <ChartEmpty title="Sin datos por país" detail="Apenas lleguen convocatorias, esta vista empezará a mostrar el origen de la captura." />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Tags className="h-4 w-4" />
              Categorías predominantes
            </CardTitle>
            <CardDescription>Los temas más frecuentes detectados por el motor de captura.</CardDescription>
          </CardHeader>
          <CardContent className="relative h-[420px] pt-5">
            {categories.length > 0 ? (
              <Plot
                config={plotConfig}
                useResizeHandler
                style={{ width: "100%", height: "100%" }}
                data={[
                  {
                    type: "bar",
                    orientation: "h",
                    x: categories.map((item) => item.total),
                    y: categories.map((item) => item.name),
                    marker: { color: categoryTheme },
                    hovertemplate: "%{y}<br>%{x} convocatorias<extra></extra>",
                  },
                ]}
                layout={buildBaseLayout(theme, "Categorías más frecuentes", "Número de convocatorias", "Categoría", {
                  margin: { l: 140, r: 24, t: 56, b: 56 },
                })}
              />
            ) : (
              <ChartEmpty title="Sin datos por categoría" detail="Las categorías aparecerán conforme se normalicen nuevas oportunidades." />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Sparkles className="h-4 w-4" />
              Cobertura de los datos capturados
            </CardTitle>
            <CardDescription>Qué porcentaje de cada oportunidad ya está enriquecido y listo para análisis.</CardDescription>
          </CardHeader>
          <CardContent className="relative h-[420px] pt-5">
            {total > 0 ? (
              <Plot
                config={plotConfig}
                useResizeHandler
                style={{ width: "100%", height: "100%" }}
                data={[
                  {
                    type: "bar",
                    x: ["Fuente", "Resumen", "Monto", "Categorías", "Fecha de cierre"],
                    y: [
                      total ? Math.round((withSource / total) * 100) : 0,
                      total ? Math.round((withSummary / total) * 100) : 0,
                      total ? Math.round((withAmount / total) * 100) : 0,
                      total ? Math.round((withCategories / total) * 100) : 0,
                      total ? Math.round((withDate / total) * 100) : 0,
                    ],
                    marker: { color: accentTheme },
                    hovertemplate: "%{x}<br>%{y}% de cobertura<extra></extra>",
                  },
                ]}
                layout={buildBaseLayout(theme, "Cobertura de datos", "Campo", "Porcentaje de cobertura", {
                  yaxis: {
                    title: { text: "Porcentaje de cobertura", font: { color: plotColors(theme).muted }, standoff: 18 },
                    tickfont: { color: plotColors(theme).text },
                    automargin: true,
                    gridcolor: plotColors(theme).grid,
                    zeroline: false,
                    range: [0, 100],
                  },
                  margin: { l: 88, r: 24, t: 56, b: 84 },
                })}
              />
            ) : (
              <ChartEmpty title="Sin cobertura por medir" detail="Cuando haya convocatorias, aquí verás qué tanto contenido quedó enriquecido." />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Search className="h-4 w-4" />
              Oportunidades recientes
            </CardTitle>
            <CardDescription>Título, fuente, entidad, estado, cierre y monto.</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Título</TableHead>
                  <TableHead>Fuente</TableHead>
                  <TableHead>Entidad</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Cierre</TableHead>
                  <TableHead>Monto</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentOpportunityItems.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="max-w-[22rem]">
                      <Link href={`/opportunities/${item.id}`} className="block font-medium text-slate-950 hover:underline dark:text-white">
                        <span className="line-clamp-2">{item.title}</span>
                      </Link>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{item.country}</p>
                    </TableCell>
                    <TableCell className="max-w-48">
                      <span className="block truncate text-sm text-slate-700 dark:text-slate-300">{sourceName(item, healthItems)}</span>
                    </TableCell>
                    <TableCell>{item.entity}</TableCell>
                    <TableCell>
                      <Badge tone={item.status}>{translateOpportunityStatus(item.status)}</Badge>
                    </TableCell>
                    <TableCell>{item.close_date ? new Date(item.close_date).toLocaleDateString("es-CO") : "Sin fecha"}</TableCell>
                    <TableCell className="max-w-40 break-words text-slate-700 dark:text-slate-300">{formatAmount(item)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <AlertTriangle className="h-4 w-4" />
              Fuentes que piden atención
            </CardTitle>
            <CardDescription>Prioriza por fallos recientes, degradación y salud operativa.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 pt-5">
            {attentionSources.length ? (
              attentionSources.slice(0, 4).map((item) => (
                <div key={item.source_id} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-medium text-slate-950 dark:text-white">{item.name}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">{item.key}</p>
                    </div>
                    <Badge tone={item.status}>{translateSourceHealthStatus(item.status)}</Badge>
                  </div>
                  <div className="mt-3 grid gap-1 text-sm text-slate-700 dark:text-slate-300">
                    <p>Éxito: {formatPercent(item.success_rate)}</p>
                    <p>Fallos: {formatPercent(item.failure_rate)}</p>
                    <p>Ítems: {formatNumber(item.average_items_found)}</p>
                    <p>Último éxito: {formatDays(item.days_since_last_success)}</p>
                    <p>Duración: {formatDuration(item.last_run_duration_seconds)}</p>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
                Todas las fuentes están en estado sano.
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <CalendarClock className="h-4 w-4" />
              Cierres por mes
            </CardTitle>
            <CardDescription>Convocatorias con fecha de cierre conocida.</CardDescription>
          </CardHeader>
          <CardContent className="relative h-[360px] pt-5">
            {months.length > 0 ? (
              <Plot
                config={plotConfig}
                useResizeHandler
                style={{ width: "100%", height: "100%" }}
                data={[
                  {
                    type: "scatter",
                    mode: "lines+markers",
                    x: months.map((item) => item.month),
                    y: months.map((item) => item.total),
                    line: { color: greenTheme, width: 3 },
                    marker: { color: greenTheme, size: 8 },
                    hovertemplate: "%{x}<br>%{y} convocatorias<extra></extra>",
                  },
                ]}
                layout={buildBaseLayout(theme, "Convocatorias con cierre conocido", "Mes de cierre", "Número de convocatorias", {
                  margin: { l: 88, r: 24, t: 56, b: 92 },
                  xaxis: {
                    title: { text: "Mes de cierre", font: { color: plotColors(theme).muted }, standoff: 18 },
                    tickangle: -35,
                    automargin: true,
                    gridcolor: plotColors(theme).grid,
                    tickfont: { color: plotColors(theme).text },
                  },
                })}
              />
            ) : (
              <ChartEmpty title="Sin cierres conocidos" detail="Esta vista se activará cuando el scraping capture fechas de cierre." />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <BarChart3 className="h-4 w-4" />
              Salud de las fuentes
            </CardTitle>
            <CardDescription>Distribución de salud operativa del scraping programado.</CardDescription>
          </CardHeader>
          <CardContent className="relative h-[360px] pt-5">
            {healthCounts.healthy + healthCounts.degraded + healthCounts.failing + healthCounts.idle > 0 ? (
              <Plot
                config={plotConfig}
                useResizeHandler
                style={{ width: "100%", height: "100%" }}
                data={[
                  {
                    type: "bar",
                    orientation: "h",
                    y: ["Sana", "Degradada", "Fallando", "Inactiva"],
                    x: [healthCounts.healthy, healthCounts.degraded, healthCounts.failing, healthCounts.idle],
                    marker: { color: [greenTheme, "#f59e0b", redTheme, "#94a3b8"] },
                    hovertemplate: "%{y}<br>%{x} fuentes<extra></extra>",
                  },
                ]}
                layout={buildBaseLayout(theme, "Salud de fuentes", "Número de fuentes", "Estado", {
                  margin: { l: 140, r: 28, t: 56, b: 56 },
                  xaxis: {
                    title: { text: "Número de fuentes", font: { color: plotColors(theme).muted }, standoff: 18 },
                    tickfont: { color: plotColors(theme).text },
                    automargin: true,
                    gridcolor: plotColors(theme).grid,
                    zeroline: false,
                  },
                  yaxis: {
                    title: { text: "Estado", font: { color: plotColors(theme).muted }, standoff: 18 },
                    tickfont: { color: plotColors(theme).text },
                    automargin: true,
                    gridcolor: plotColors(theme).grid,
                    zeroline: false,
                  },
                })}
              />
            ) : (
              <ChartEmpty title="Sin salud para mostrar" detail="Aún no se han cargado fuentes suficientes para esta vista." />
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
          <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
            <MapPinned className="h-4 w-4" />
            Fuentes más activas
          </CardTitle>
          <CardDescription>Ordenadas por volumen reciente detectado en el scraping.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Fuente</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Corridas</TableHead>
                <TableHead>Ítems detectados</TableHead>
                <TableHead>Éxito</TableHead>
                <TableHead>Último éxito</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {topActiveSources.map((item) => (
                <TableRow key={item.source_id}>
                  <TableCell>
                    <div>
                      <p className="font-medium text-slate-950 dark:text-white">{item.name}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">{item.key}</p>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge tone={item.status}>{translateSourceHealthStatus(item.status)}</Badge>
                  </TableCell>
                  <TableCell>{item.recent_runs}</TableCell>
                  <TableCell>{formatNumber(item.recent_items_found)}</TableCell>
                  <TableCell>{formatPercent(item.success_rate)}</TableCell>
                  <TableCell>{formatDays(item.days_since_last_success)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
          <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
            <RefreshCcw className="h-4 w-4" />
            Corridas recientes del scraping
          </CardTitle>
          <CardDescription>Estado, volumen y errores de las últimas ejecuciones.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Fuente</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Encontradas</TableHead>
                <TableHead>Creadas</TableHead>
                <TableHead>Actualizadas</TableHead>
                <TableHead>Error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runItems.slice(0, 8).map((run) => (
                <TableRow key={run.id}>
                  <TableCell>
                    <div>
                      <p className="font-medium text-slate-950 dark:text-white">{run.source_name}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">{run.source_key}</p>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge tone={run.status === "failed" ? "closed" : run.status === "scheduled" ? "closing_soon" : "open"}>
                      {translateOperationalStatus(run.status)}
                    </Badge>
                  </TableCell>
                  <TableCell>{run.items_found}</TableCell>
                  <TableCell>{run.items_created}</TableCell>
                  <TableCell>{run.items_updated}</TableCell>
                  <TableCell className="max-w-80 truncate text-xs text-slate-500 dark:text-slate-400">{run.error_message ?? "Sin error"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
          <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
            <Sparkles className="h-4 w-4" />
            Actividad interna
          </CardTitle>
            <CardDescription>Resumen de tareas, automatizaciones y procesos de soporte.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tipo</TableHead>
                <TableHead>Proveedor</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Resultado</TableHead>
                <TableHead>Fecha</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {taskItems.slice(0, 6).map((task) => (
                <TableRow key={task.id}>
                  <TableCell className="font-medium text-slate-950 dark:text-white">{task.task_type}</TableCell>
                  <TableCell>{task.provider}</TableCell>
                  <TableCell>
                    <Badge tone={task.status === "failed" ? "closed" : task.status === "queued" ? "closing_soon" : "open"}>
                      {translateOperationalStatus(task.status)}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-72 truncate text-xs text-slate-500 dark:text-slate-400">
                    {task.error_message ?? JSON.stringify(task.result)}
                  </TableCell>
                  <TableCell>{new Date(task.created_at).toLocaleString("es-CO")}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  );
}

function StatCard({ label, value, detail }: { label: string; value: string | number; detail: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{label}</p>
        <p className="mt-1 text-2xl font-semibold text-slate-950 dark:text-white">{value}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">{detail}</p>
      </CardContent>
    </Card>
  );
}

function InfoTile({ label, value, detail }: { label: string; value: string | number; detail: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-950 dark:text-white">{value}</p>
      <p className="text-xs text-slate-500 dark:text-slate-400">{detail}</p>
    </div>
  );
}

function ChartEmpty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-100/30 px-6 text-center dark:border-slate-700 dark:bg-slate-800/30">
      <p className="text-sm font-medium text-slate-950 dark:text-white">{title}</p>
      <p className="mt-1 max-w-md text-sm text-slate-500 dark:text-slate-400">{detail}</p>
    </div>
  );
}
