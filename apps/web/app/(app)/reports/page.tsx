"use client";

import { Download, FileSpreadsheet, FileText, FileType, RefreshCcw, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, downloadReport } from "@/lib/api";
import type { Report, ReportFormat } from "@/lib/types";

const formats: Array<{ format: ReportFormat; label: string; icon: typeof FileText }> = [
  { format: "html", label: "HTML", icon: FileText },
  { format: "pdf", label: "PDF", icon: FileType },
  { format: "csv", label: "CSV", icon: FileSpreadsheet },
  { format: "xlsx", label: "Excel", icon: FileSpreadsheet },
];

function formatLabel(value: string) {
  const map: Record<string, string> = {
    html: "HTML",
    pdf: "PDF",
    csv: "CSV",
    xlsx: "Excel",
  };
  return map[value] ?? value;
}

function ReportCard({ report }: { report: Report }) {
  const queryClient = useQueryClient();
  const downloadLabel = `Descargar ${formatLabel(report.format)}`;
  const download = useMutation({
    mutationFn: () => downloadReport(report),
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo descargar"),
  });
  const regenerate = useMutation({
    mutationFn: () => api.regenerateReport(report.id),
    onSuccess: () => {
      toast.success("Reporte regenerado");
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo regenerar"),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteReport(report.id),
    onSuccess: () => {
      toast.success("Reporte eliminado");
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo eliminar"),
  });

  return (
    <Card>
      <CardHeader className="border-b border-border/70 pb-4">
        <CardTitle className="flex items-center justify-between gap-3 text-slate-950 dark:text-white">
          <span className="flex min-w-0 items-center gap-2">
            <FileText className="h-4 w-4 shrink-0" />
            <span className="truncate">{report.title}</span>
          </span>
          <Badge tone="medium">{formatLabel(report.format)}</Badge>
        </CardTitle>
        <CardDescription>
          Tipo: {report.report_type} · Generado: {new Date(report.generated_at).toLocaleString("es-CO")} · Estado: {report.status}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        <div className="max-h-44 overflow-hidden rounded-lg border border-border bg-muted/40 p-3 text-xs text-slate-700 dark:text-slate-300">
          {report.html_content.replace(/<[^>]+>/g, " ").slice(0, 300)}
        </div>
        <div className="rounded-xl border border-dashed border-border/80 bg-background/60 p-4 dark:bg-slate-950/30">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">Descarga directa</p>
          <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
            Archivo listo para bajar en formato {formatLabel(report.format)}.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => download.mutate()} disabled={download.isPending}>
              <Download className="h-4 w-4" />
              {downloadLabel}
            </Button>
            <Button variant="outline" onClick={() => regenerate.mutate()} disabled={regenerate.isPending}>
              <RefreshCcw className="h-4 w-4" />
              Regenerar
            </Button>
            <Button variant="outline" size="icon" title="Eliminar" onClick={() => remove.mutate()} disabled={remove.isPending}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function ReportsPage() {
  const queryClient = useQueryClient();
  const reports = useQuery({ queryKey: ["reports"], queryFn: api.reports });
  const createReport = useMutation({
    mutationFn: (format: ReportFormat) =>
      api.createReport({
        title: `Reporte ejecutivo de convocatorias (${formatLabel(format)})`,
        format,
        report_type: "custom",
      }),
    onSuccess: () => {
      toast.success("Reporte generado");
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo generar el reporte"),
  });

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Reportes</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            Generación en HTML, PDF y exportaciones para dirección, análisis y seguimiento operativo.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {formats.map((item) => {
            const Icon = item.icon;
            return (
              <Button key={item.format} onClick={() => createReport.mutate(item.format)} disabled={createReport.isPending}>
                <Icon className="h-4 w-4" />
                {item.label}
              </Button>
            );
          })}
        </div>
      </div>
      {reports.isLoading ? <LoadingState label="Cargando reportes" /> : null}
      {reports.error ? <ErrorState message={reports.error.message} /> : null}
      {reports.data && reports.data.length === 0 ? (
        <EmptyState title="No hay reportes" detail="Genera un reporte HTML, PDF, CSV o Excel." />
      ) : null}
      <div className="grid gap-4 md:grid-cols-2">
        {(reports.data ?? []).map((report) => (
          <ReportCard key={report.id} report={report} />
        ))}
      </div>
    </section>
  );
}
