"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  MapPinned,
  Radar,
  Sparkles,
  Target,
  TrendingUp,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { decodeVisibleText, isNoiseVisibleText } from "@/lib/text";
import type { DashboardOpportunityItem } from "@/lib/types";

const STATUS_COLORS = ["#16a34a", "#f59e0b", "#64748b", "#94a3b8"];
const COUNTRY_COLORS = ["#0ea5e9", "#6366f1", "#14b8a6", "#f97316", "#ec4899", "#8b5cf6", "#22c55e", "#eab308"];

function formatNumber(value: number) {
  return new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 }).format(value);
}

function formatPercent(value: number) {
  return `${Math.round(value)}%`;
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

function translatePriority(priority: string | null) {
  const map: Record<string, string> = {
    high: "Alta",
    medium: "Media",
    low: "Baja",
    not_recommended: "No recomendada",
  };
  return priority ? (map[priority] ?? priority) : "Sin score";
}

function formatAmount(item: DashboardOpportunityItem) {
  if (item.funding_amount_raw?.trim()) return decodeVisibleText(item.funding_amount_raw, "Por validar");
  if (item.funding_amount_value === null) return "Por validar";
  const currency = item.funding_amount_currency ? ` ${item.funding_amount_currency}` : "";
  return `${formatNumber(item.funding_amount_value)}${currency}`;
}

function visibleTitle(title: string) {
  const text = decodeVisibleText(title, "");
  return isNoiseVisibleText(text) ? "Convocatoria sin título legible" : text || "Convocatoria sin título legible";
}

function OpportunityRow({ item }: { item: DashboardOpportunityItem }) {
  return (
    <TableRow>
      <TableCell className="max-w-xs">
        <Link href={`/opportunities/${item.id}`} className="font-medium text-slate-950 hover:text-cyan-700 dark:text-white dark:hover:text-cyan-200">
          {visibleTitle(item.title)}
        </Link>
        <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">{decodeVisibleText(item.entity)}</p>
      </TableCell>
      <TableCell>{item.country || "Sin dato"}</TableCell>
      <TableCell>
        {item.score !== null ? (
          <div className="space-y-1">
            <p className="font-medium text-slate-950 dark:text-white">{Math.round(item.score)}</p>
            <Badge tone={item.priority ?? "medium"}>{translatePriority(item.priority)}</Badge>
          </div>
        ) : (
          <span className="text-xs text-slate-500 dark:text-slate-400">Sin calcular</span>
        )}
      </TableCell>
      <TableCell>
        {item.days_to_close !== null ? (
          <span>{item.days_to_close} d</span>
        ) : (
          <Badge tone={item.status}>{translateOpportunityStatus(item.status)}</Badge>
        )}
      </TableCell>
      <TableCell className="text-xs text-slate-500 dark:text-slate-400">{formatAmount(item)}</TableCell>
    </TableRow>
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

function ChartEmpty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="flex h-full min-h-[280px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-100/30 px-6 text-center dark:border-slate-700 dark:bg-slate-800/30">
      <p className="text-sm font-medium text-slate-950 dark:text-white">{title}</p>
      <p className="mt-1 max-w-md text-sm text-slate-500 dark:text-slate-400">{detail}</p>
    </div>
  );
}

export default function DashboardPage() {
  const summary = useQuery({ queryKey: ["dashboard-summary"], queryFn: api.dashboardSummary });

  const statusChart = useMemo(() => summary.data?.status_breakdown ?? [], [summary.data?.status_breakdown]);
  const countryChart = useMemo(() => summary.data?.country_breakdown ?? [], [summary.data?.country_breakdown]);

  if (summary.isLoading) return <LoadingState label="Cargando panel analítico" />;
  if (summary.error) return <ErrorState message={summary.error.message} />;
  if (!summary.data) return <EmptyState title="Sin datos del panel" detail="No se recibió información del servidor." />;

  const data = summary.data;
  const attentionSources = data.degraded_sources + data.failing_sources;
  const profileIncomplete = data.profile.completeness < 80;

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-cyan-700 dark:text-cyan-200">
            <Radar className="h-5 w-5" />
            <span className="text-xs font-medium uppercase tracking-[0.22em]">ConvocaRadar IA</span>
          </div>
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Panel analítico</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
              Prioriza convocatorias con score real, detecta cierres próximos y revisa la salud resumida de tus fuentes.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/opportunities"
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-4 text-sm font-medium text-slate-900 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800"
          >
            <Target className="h-4 w-4" />
            Ver convocatorias
          </Link>
          <Link
            href="/onboarding"
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90"
          >
            <Sparkles className="h-4 w-4" />
            Perfil institucional
          </Link>
        </div>
      </div>

      {profileIncomplete ? (
        <Card className="border-cyan-500/30 bg-cyan-500/5">
          <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-medium text-slate-950 dark:text-white">
                Perfil al {formatPercent(data.profile.completeness)} — mejora la compatibilidad de tus scores
              </p>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                Falta completar: {data.profile.missing_fields.join(", ")}.
              </p>
            </div>
            <Link
              href="/onboarding"
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-4 text-sm font-medium text-slate-900 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800"
            >
              Completar perfil
              <ArrowRight className="h-4 w-4" />
            </Link>
          </CardContent>
        </Card>
      ) : null}

      {attentionSources > 0 ? (
        <Card className="border-amber-500/30 bg-amber-500/5">
          <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-600 dark:text-amber-300" />
              <div>
                <p className="text-sm font-medium text-slate-950 dark:text-white">
                  {attentionSources} fuente{attentionSources === 1 ? "" : "s"} requiere{attentionSources === 1 ? "" : "n"} atención
                </p>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                  {data.source_alerts.map((item) => item.name).join(", ") || "Revisa el estado operativo de tus conectores."}
                </p>
              </div>
            </div>
            <Link
              href="/sources"
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-4 text-sm font-medium text-slate-900 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800"
            >
              Ver fuentes
              <ArrowRight className="h-4 w-4" />
            </Link>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total convocatorias" value={formatNumber(data.total_opportunities)} detail="En tu alcance organizacional" />
        <StatCard label="Convocatorias abiertas" value={formatNumber(data.open_opportunities)} detail="Vigentes para postulación" />
        <StatCard label="Cierran pronto" value={formatNumber(data.closing_soon_opportunities)} detail="Requieren seguimiento inmediato" />
        <StatCard label="Alta compatibilidad" value={formatNumber(data.high_match_opportunities)} detail="Score prioritario alto" />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <TrendingUp className="h-4 w-4" />
              Top compatibilidad
            </CardTitle>
            <CardDescription>Convocatorias con mejor score según tu perfil institucional.</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            {data.top_scored.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Convocatoria</TableHead>
                    <TableHead>País</TableHead>
                    <TableHead>Score</TableHead>
                    <TableHead>Plazo</TableHead>
                    <TableHead>Monto</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.top_scored.map((item) => (
                    <OpportunityRow key={item.id} item={item} />
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-6">
                <EmptyState
                  title="Sin scores todavía"
                  detail="Completa tu perfil institucional y espera el cálculo automático de compatibilidad."
                />
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <CalendarClock className="h-4 w-4" />
              Cierran pronto
            </CardTitle>
            <CardDescription>Convocatorias con fecha de cierre cercana.</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            {data.closing_soon.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Convocatoria</TableHead>
                    <TableHead>País</TableHead>
                    <TableHead>Score</TableHead>
                    <TableHead>Plazo</TableHead>
                    <TableHead>Monto</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.closing_soon.map((item) => (
                    <OpportunityRow key={item.id} item={item} />
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-6">
                <EmptyState title="Sin cierres próximos" detail="No hay convocatorias marcadas como cierre próximo en este momento." />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <TrendingUp className="h-4 w-4" />
              Estado de convocatorias
            </CardTitle>
            <CardDescription>Distribución agregada en servidor, sin muestreo parcial.</CardDescription>
          </CardHeader>
          <CardContent className="h-[320px] pt-5">
            {statusChart.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={statusChart} layout="vertical" margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} className="stroke-slate-200 dark:stroke-slate-700" />
                  <XAxis type="number" allowDecimals={false} tick={{ fill: "currentColor", fontSize: 12 }} />
                  <YAxis type="category" dataKey="name" width={110} tick={{ fill: "currentColor", fontSize: 12 }} />
                  <Tooltip
                    formatter={(value: number) => [formatNumber(value), "Convocatorias"]}
                    contentStyle={{ borderRadius: 8, borderColor: "rgba(148,163,184,0.35)" }}
                  />
                  <Bar dataKey="total" radius={[0, 6, 6, 0]}>
                    {statusChart.map((entry, index) => (
                      <Cell key={entry.name} fill={STATUS_COLORS[index % STATUS_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <ChartEmpty title="Sin convocatorias visibles" detail="Ejecuta captura o revisa tus fuentes para poblar el tablero." />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <MapPinned className="h-4 w-4" />
              Convocatorias por país
            </CardTitle>
            <CardDescription>Top países con mayor volumen detectado.</CardDescription>
          </CardHeader>
          <CardContent className="h-[320px] pt-5">
            {countryChart.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={countryChart} margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-slate-200 dark:stroke-slate-700" />
                  <XAxis dataKey="name" tick={{ fill: "currentColor", fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={70} />
                  <YAxis allowDecimals={false} tick={{ fill: "currentColor", fontSize: 12 }} />
                  <Tooltip
                    formatter={(value: number) => [formatNumber(value), "Convocatorias"]}
                    contentStyle={{ borderRadius: 8, borderColor: "rgba(148,163,184,0.35)" }}
                  />
                  <Bar dataKey="total" radius={[6, 6, 0, 0]}>
                    {countryChart.map((entry, index) => (
                      <Cell key={entry.name} fill={COUNTRY_COLORS[index % COUNTRY_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <ChartEmpty title="Sin distribución por país" detail="Todavía no hay convocatorias georreferenciadas para graficar." />
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
          <CardTitle className="text-slate-950 dark:text-white">Calidad de datos</CardTitle>
          <CardDescription>Cobertura agregada de campos útiles para alertas y scoring.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 pt-5 sm:grid-cols-2 xl:grid-cols-5">
          <StatCard label="Con resumen" value={formatNumber(data.data_coverage.with_summary)} detail="Texto sintetizado disponible" />
          <StatCard label="Con monto" value={formatNumber(data.data_coverage.with_amount)} detail="Valor numérico o bruto" />
          <StatCard label="Con fecha cierre" value={formatNumber(data.data_coverage.with_close_date)} detail="Fecha utilizable para alertas" />
          <StatCard label="Con fuente" value={formatNumber(data.data_coverage.with_source)} detail="Trazabilidad del conector" />
          <StatCard label="Cobertura embeddings" value={formatPercent(data.data_coverage.embeddings_coverage)} detail="Búsqueda semántica" />
        </CardContent>
      </Card>
    </section>
  );
}
