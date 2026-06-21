"use client";

import { AlertTriangle, Activity, Database, RefreshCcw, ShieldCheck, WandSparkles } from "lucide-react";
import type { ElementType } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";

export default function AdminPage() {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const sourceHealth = useQuery({ queryKey: ["source-health"], queryFn: api.sourceHealth });
  const sourceRunsOverview = useQuery({ queryKey: ["source-runs-overview"], queryFn: api.sourceRunsOverview });
  const auditLogs = useQuery({ queryKey: ["audit-logs"], queryFn: api.auditLogs });
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: api.tasks });
  const metrics = useQuery({ queryKey: ["admin-metrics"], queryFn: api.adminMetrics });

  const retrySources = useMutation({
    mutationFn: api.retryDegradedSources,
    onSuccess: async (payload) => {
      toast.success(`Reintentos programados: ${payload.scheduled}`);
      await queryClient.invalidateQueries({ queryKey: ["source-health"] });
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
      await queryClient.invalidateQueries({ queryKey: ["admin-metrics"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudieron programar reintentos"),
  });

  if (
    me.isLoading ||
    sources.isLoading ||
    sourceHealth.isLoading ||
    sourceRunsOverview.isLoading ||
    auditLogs.isLoading ||
    tasks.isLoading ||
    metrics.isLoading
  ) {
    return <LoadingState label="Cargando panel admin" />;
  }

  if (me.error) return <ErrorState message={me.error.message} />;
  if (auditLogs.error) return <ErrorState message={auditLogs.error.message} />;
  if (metrics.error) return <ErrorState message={metrics.error.message} />;
  if (sourceRunsOverview.error) return <ErrorState message={sourceRunsOverview.error.message} />;
  if (sourceHealth.error) return <ErrorState message={sourceHealth.error.message} />;

  const healthItems = sourceHealth.data ?? [];
  const runs = sourceRunsOverview.data ?? [];

  const healthCounts = {
    healthy: healthItems.filter((item) => item.status === "healthy").length,
    degraded: healthItems.filter((item) => item.status === "degraded").length,
    failing: healthItems.filter((item) => item.status === "failing").length,
    idle: healthItems.filter((item) => item.status === "idle").length,
  };

  const runCounts = {
    success: runs.filter((item) => item.status === "success").length,
    failed: runs.filter((item) => item.status === "failed").length,
    queued: runs.filter((item) => item.status === "queued").length,
    scheduled: runs.filter((item) => item.status === "scheduled").length,
    running: runs.filter((item) => item.status === "running").length,
  };

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Panel admin</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            Salud operativa, configuración de IA, auditoría y control de fuentes.
          </p>
        </div>
        <Button variant="outline" onClick={() => retrySources.mutate()} disabled={retrySources.isPending}>
          <RefreshCcw className={`h-4 w-4 ${retrySources.isPending ? "animate-spin" : ""}`} />
          {retrySources.isPending ? "Programando..." : "Reintentar fuentes degradadas"}
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <AdminCard icon={ShieldCheck} title="Rol actual" value={me.data?.role ?? "admin"} detail={me.data?.email ?? ""} />
        <AdminCard icon={Database} title="Fuentes configuradas" value={String(sources.data?.length ?? 0)} detail="Incluye fuentes globales y de organización" />
        <AdminCard icon={WandSparkles} title="Tareas registradas" value={String(tasks.data?.length ?? 0)} detail="Scraping, IA, reportes y alertas" />
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <MetricCard label="Fuentes sanas" value={healthCounts.healthy} detail="Operando con normalidad" />
        <MetricCard label="Fuentes degradadas" value={healthCounts.degraded} detail="Fallas parciales" />
        <MetricCard label="Fuentes fallando" value={healthCounts.failing} detail="Requieren revisión inmediata" />
        <MetricCard label="Fuentes inactivas" value={healthCounts.idle} detail="Sin corridas recientes" />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <MetricCard label="Corridas exitosas" value={runCounts.success} detail="Últimas ejecuciones correctas" />
        <MetricCard label="Corridas con problema" value={runCounts.failed} detail="Fallidas, en cola o programadas" />
      </div>

      <Card>
        <CardHeader className="border-b border-border/70 pb-4">
          <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
            <AlertTriangle className="h-4 w-4" />
            Fuentes con riesgo
          </CardTitle>
          <CardDescription>Fuentes degradadas, fallando o sin actividad reciente.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 pt-5 md:grid-cols-2">
          {healthItems.filter((item) => item.status !== "healthy").length > 0 ? (
            healthItems
              .filter((item) => item.status !== "healthy")
              .map((item) => (
                <div key={item.source_id} className="rounded-lg border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-slate-950 dark:text-white">{item.name}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">{item.key}</p>
                    </div>
                    <Badge tone={item.status}>{item.status}</Badge>
                  </div>
                  <div className="mt-3 grid gap-1 text-sm text-slate-700 dark:text-slate-300">
                    <p>Éxito: {Math.round(item.success_rate)}%</p>
                    <p>Fallos: {Math.round(item.failure_rate)}%</p>
                    <p>Ítems detectados: {item.recent_items_found}</p>
                    <p>Último éxito: {item.days_since_last_success ?? "Sin dato"} d</p>
                    <p className="truncate text-xs text-slate-500 dark:text-slate-400">{item.last_error ?? item.last_run_status ?? "Sin error reciente"}</p>
                  </div>
                </div>
              ))
          ) : (
            <div className="rounded-lg border border-border bg-card p-4 text-sm text-slate-500 dark:text-slate-400">
              No hay fuentes con riesgo en este momento.
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-border/70 pb-4">
          <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
            <Activity className="h-4 w-4" />
            Corridas recientes
          </CardTitle>
          <CardDescription>Últimas ejecuciones de scraping con la fuente asociada.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto pt-5">
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
              {runs.slice(0, 10).map((run) => (
                <TableRow key={run.id}>
                  <TableCell>
                    <div>
                      <p className="font-medium text-slate-950 dark:text-white">{run.source_name}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">{run.source_key}</p>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge tone={run.status === "failed" ? "closed" : run.status === "scheduled" ? "closing_soon" : "open"}>{run.status}</Badge>
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
        <CardHeader className="border-b border-border/70 pb-4">
          <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
            <ShieldCheck className="h-4 w-4" />
            Auditoría reciente
          </CardTitle>
          <CardDescription>Acciones sensibles y trazabilidad.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto pt-5">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Acción</TableHead>
                <TableHead>Recurso</TableHead>
                <TableHead>ID</TableHead>
                <TableHead>Fecha</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(auditLogs.data ?? []).map((log) => (
                <TableRow key={log.id}>
                  <TableCell className="font-medium">{log.action}</TableCell>
                  <TableCell>{log.resource_type}</TableCell>
                  <TableCell className="max-w-52 truncate text-xs text-slate-500 dark:text-slate-400">{log.resource_id ?? "n/a"}</TableCell>
                  <TableCell>{new Date(log.created_at).toLocaleString("es-CO")}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  );
}

function AdminCard({ icon: Icon, title, value, detail }: { icon: ElementType; title: string; value: string; detail: string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-5">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-cyan-400/15 bg-cyan-400/10 text-cyan-700 dark:text-cyan-200">
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{title}</p>
          <p className="text-lg font-semibold text-slate-950 dark:text-white">{value}</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">{detail}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function MetricCard({ label, value, detail }: { label: string; value: number; detail: string }) {
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
