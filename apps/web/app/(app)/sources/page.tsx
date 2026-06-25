"use client";

import { AlertTriangle, Play, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { SourceHealth } from "@/lib/types";

function translateSourceStatus(status: string) {
  const map: Record<string, string> = {
    healthy: "Sana",
    degraded: "Degradada",
    failing: "Fallando",
    idle: "Inactiva",
  };
  return map[status] ?? status;
}

function translateRunStatus(status: string) {
  const map: Record<string, string> = {
    success: "Éxito",
    failed: "Fallida",
    queued: "En cola",
    running: "En ejecución",
    scheduled: "Programada",
    pending: "Pendiente",
  };
  return map[status] ?? status;
}

function formatPercent(value: number) {
  return `${Math.round(value)}%`;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("es-CO", { maximumFractionDigits: 1 }).format(value);
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

export default function SourcesPage() {
  const queryClient = useQueryClient();
  const [sourceType, setSourceType] = useState("html");
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const sourceHealth = useQuery({ queryKey: ["source-health"], queryFn: api.sourceHealth });
  const actionLinkClass =
    "inline-flex h-8 items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-xs font-medium text-slate-900 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800";

  const healthItems = useMemo(() => sourceHealth.data ?? [], [sourceHealth.data]);

  const healthSummary = useMemo(() => {
    if (!healthItems.length) {
      return { avgSuccess: 0, avgFailure: 0, avgItems: 0, avgDuration: 0, stale: 0 };
    }
    const avgSuccess = healthItems.reduce((sum, item) => sum + item.success_rate, 0) / healthItems.length;
    const avgFailure = healthItems.reduce((sum, item) => sum + item.failure_rate, 0) / healthItems.length;
    const avgItems = healthItems.reduce((sum, item) => sum + item.average_items_found, 0) / healthItems.length;
    const durationItems = healthItems.filter((item) => item.last_run_duration_seconds !== null);
    const avgDuration = durationItems.length
      ? durationItems.reduce((sum, item) => sum + (item.last_run_duration_seconds ?? 0), 0) / durationItems.length
      : 0;
    const stale = healthItems.filter((item) => (item.days_since_last_success ?? Number.POSITIVE_INFINITY) >= 7).length;
    return { avgSuccess, avgFailure, avgItems, avgDuration, stale };
  }, [healthItems]);

  const createSource = useMutation({
    mutationFn: api.createSource,
    onSuccess: () => {
      toast.success("Fuente creada");
      queryClient.invalidateQueries({ queryKey: ["sources"] });
      queryClient.invalidateQueries({ queryKey: ["source-health"] });
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      queryClient.invalidateQueries({ queryKey: ["admin-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["source-runs-overview"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo crear la fuente"),
  });

  const runSource = useMutation({
    mutationFn: api.runSource,
    onSuccess: (run) => {
      const status = typeof run === "object" && run && "status" in run ? String(run.status) : "success";
      toast.success(status === "queued" ? "Ejecución encolada" : "Ejecución completada");
      queryClient.invalidateQueries({ queryKey: ["sources"] });
      queryClient.invalidateQueries({ queryKey: ["source-health"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      queryClient.invalidateQueries({ queryKey: ["admin-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["source-runs-overview"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo ejecutar la fuente"),
  });

  const runAllSources = useMutation({
    mutationFn: api.runAllSources,
    onSuccess: () => {
      toast.success("Se lanzaron todas las fuentes");
      queryClient.invalidateQueries({ queryKey: ["sources"] });
      queryClient.invalidateQueries({ queryKey: ["source-health"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      queryClient.invalidateQueries({ queryKey: ["admin-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["source-runs-overview"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo lanzar la corrida masiva"),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const baseUrl = String(form.get("base_url"));
    let hostname = "";
    try {
      hostname = new URL(baseUrl).hostname;
    } catch {
      hostname = "";
    }

    createSource.mutate({
      name: form.get("name"),
      key: form.get("key"),
      base_url: baseUrl,
      country: form.get("country") || "Colombia",
      region: form.get("region") || "LatAm",
      source_type: sourceType,
      category: String(form.get("category") || "innovacion")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      allowed_domains: hostname ? [hostname] : [],
    });
    event.currentTarget.reset();
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Fuentes</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            Configura fuentes HTML, API, PDF, RSS, manuales o híbridas.
          </p>
        </div>
        <Button variant="outline" onClick={() => runAllSources.mutate()} disabled={runAllSources.isPending}>
          <RefreshCw className="h-4 w-4" />
          Ejecutar todas
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard title="Fuentes activas" value={String(sources.data?.filter((source) => source.enabled).length ?? 0)} detail="Conectadas y listas para ejecutar" />
        <MetricCard title="Éxito promedio" value={formatPercent(healthSummary.avgSuccess)} detail="Éxito reciente por fuente" />
        <MetricCard title="Fallo promedio" value={formatPercent(healthSummary.avgFailure)} detail="Corridas fallidas recientes" />
        <MetricCard title="Ítems promedio" value={formatNumber(healthSummary.avgItems)} detail="Resultados por corrida" />
        <MetricCard title="Fuentes obsoletas" value={String(healthSummary.stale)} detail="Sin éxito reciente suficiente" />
        <MetricCard title="Duración media" value={formatDuration(healthSummary.avgDuration)} detail="Tiempo promedio de scraping" />
      </div>

      <Card>
        <CardHeader className="border-b border-border/70 pb-4">
          <CardTitle className="text-slate-950 dark:text-white">Nueva fuente</CardTitle>
          <CardDescription>Alta rápida con tipo html, api, rss, hybrid, pdf o manual.</CardDescription>
        </CardHeader>
        <CardContent className="pt-5">
          <form className="grid gap-3 md:grid-cols-4" onSubmit={submit}>
            <Input name="name" placeholder="Nombre" required />
            <Input name="key" placeholder="Clave única" required />
            <Input name="base_url" placeholder="https://..." required />
            <Input name="country" placeholder="País" defaultValue="Colombia" />
            <Input name="region" placeholder="Región" defaultValue="LatAm" />
            <Input name="category" placeholder="Categorías (coma)" defaultValue="innovacion" />
            <label className="flex flex-col gap-1 text-sm text-slate-700 dark:text-slate-300">
              Tipo de fuente
              <Select
                name="source_type"
                value={sourceType}
                onChange={(event) => setSourceType(event.target.value)}
              >
                <option value="html">html</option>
                <option value="api">api</option>
                <option value="rss">rss</option>
                <option value="hybrid">hybrid</option>
                <option value="pdf">pdf</option>
                <option value="manual">manual</option>
              </Select>
            </label>
            <Button className="md:col-span-4" disabled={createSource.isPending}>
              <Plus className="h-4 w-4" />
              Crear fuente
            </Button>
          </form>
        </CardContent>
      </Card>

      {sources.isLoading || sourceHealth.isLoading ? <LoadingState label="Cargando fuentes" /> : null}
      {sources.error ? <ErrorState message={sources.error.message} /> : null}
      {sourceHealth.error ? <ErrorState message={sourceHealth.error.message} /> : null}

      {sources.data ? (
        <Card>
          <CardHeader className="border-b border-border/70 pb-4">
            <CardTitle className="text-slate-950 dark:text-white">Fuentes registradas</CardTitle>
            <CardDescription>Estado operativo y última ejecución de cada fuente.</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nombre</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>País</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Última ejecución</TableHead>
                  <TableHead>Acciones</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sources.data.map((source) => (
                  <TableRow key={source.id}>
                    <TableCell className="font-medium text-slate-950 dark:text-white">{source.name}</TableCell>
                    <TableCell>{source.source_type}</TableCell>
                    <TableCell>{source.country}</TableCell>
                    <TableCell>
                      <Badge tone={source.enabled ? "open" : "closed"}>{source.enabled ? "activa" : "inactiva"}</Badge>
                    </TableCell>
                    <TableCell>{source.last_run_at ? new Date(source.last_run_at).toLocaleString("es-CO") : "Sin ejecución"}</TableCell>
                    <TableCell>
                      <Button variant="outline" size="sm" onClick={() => runSource.mutate(source.id)} disabled={runSource.isPending}>
                        <Play className="h-4 w-4" />
                        Ejecutar
                      </Button>
                      <Link href={`/sources/${source.id}/runs`} className={`ml-2 ${actionLinkClass}`}>
                        Ejecuciones
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      {sourceHealth.data ? (
        <Card>
          <CardHeader className="border-b border-border/70 pb-4">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <AlertTriangle className="h-4 w-4" />
              Salud detallada de fuentes
            </CardTitle>
            <CardDescription>Éxito, fallos, volumen promedio y tiempo desde el último éxito por fuente.</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fuente</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Éxito</TableHead>
                  <TableHead>Fallos</TableHead>
                  <TableHead>Ítems</TableHead>
                  <TableHead>Último éxito</TableHead>
                  <TableHead>Duración</TableHead>
                  <TableHead>Último estado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {healthItems.map((item: SourceHealth) => (
                  <TableRow key={item.source_id}>
                    <TableCell>
                      <div>
                        <p className="font-medium text-slate-950 dark:text-white">{item.name}</p>
                        <p className="text-xs text-slate-500 dark:text-slate-400">{item.key}</p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge tone={item.status}>{translateSourceStatus(item.status)}</Badge>
                    </TableCell>
                    <TableCell>{formatPercent(item.success_rate)}</TableCell>
                    <TableCell>{formatPercent(item.failure_rate)}</TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span>Detectados: {formatNumber(item.recent_items_found)}</span>
                        <span className="text-xs text-slate-500 dark:text-slate-400">Promedio: {formatNumber(item.average_items_found)}</span>
                      </div>
                    </TableCell>
                    <TableCell>{formatDays(item.days_since_last_success)}</TableCell>
                    <TableCell>{formatDuration(item.last_run_duration_seconds)}</TableCell>
                    <TableCell>{translateRunStatus(item.last_run_status ?? "idle")}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      {(sourceHealth.data ?? []).some((item) => item.status !== "healthy") ? (
        <Card>
          <CardHeader className="border-b border-border/70 pb-4">
            <CardTitle className="text-slate-950 dark:text-white">Fuentes que requieren atención</CardTitle>
            <CardDescription>Prioriza las fuentes con fallas recientes, degradación o poca actividad.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 pt-5 md:grid-cols-2">
            {healthItems
              .filter((item) => item.status !== "healthy")
              .map((item) => (
                <div key={item.source_id} className="rounded-lg border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-slate-950 dark:text-white">{item.name}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">{item.key}</p>
                    </div>
                    <Badge tone={item.status}>{translateSourceStatus(item.status)}</Badge>
                  </div>
                  <div className="mt-3 grid gap-2 text-sm text-slate-700 dark:text-slate-300">
                    <p>Éxito: {formatPercent(item.success_rate)}</p>
                    <p>Fallos: {formatPercent(item.failure_rate)}</p>
                    <p>Último éxito: {formatDays(item.days_since_last_success)}</p>
                    <p>Duración: {formatDuration(item.last_run_duration_seconds)}</p>
                    <p className="truncate text-xs text-slate-500 dark:text-slate-400">{item.last_error ?? "Sin error reciente"}</p>
                  </div>
                </div>
              ))}
          </CardContent>
        </Card>
      ) : null}
    </section>
  );
}

function MetricCard({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{title}</p>
        <p className="mt-1 text-2xl font-semibold text-slate-950 dark:text-white">{value}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">{detail}</p>
      </CardContent>
    </Card>
  );
}
