"use client";

import { ArrowLeft, Clock, FileWarning } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";

export default function SourceRunsPage() {
  const params = useParams<{ id: string }>();
  const runs = useQuery({
    queryKey: ["source-runs", params.id],
    queryFn: () => api.sourceRuns(params.id),
  });

  if (runs.isLoading) return <LoadingState label="Cargando ejecuciones" />;
  if (runs.error) return <ErrorState message={runs.error.message} />;

  return (
    <section className="space-y-6">
      <Link href="/sources" className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-slate-950 dark:text-slate-400 dark:hover:text-white">
        <ArrowLeft className="h-4 w-4" />
        Volver a fuentes
      </Link>
      <div>
        <h1 className="text-2xl font-semibold text-slate-950 dark:text-white">Ejecuciones de scraping</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">Trazabilidad por fuente: estado, métricas y errores.</p>
      </div>
      {!runs.data?.length ? (
        <EmptyState title="Sin ejecuciones" detail="Ejecuta la fuente desde el panel de fuentes para crear el primer registro." />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Clock className="h-4 w-4" />
              Historial
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Estado</TableHead>
                  <TableHead>Inicio</TableHead>
                  <TableHead>Encontradas</TableHead>
                  <TableHead>Creadas</TableHead>
                  <TableHead>Actualizadas</TableHead>
                  <TableHead>Fallidas</TableHead>
                  <TableHead>Log</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.data.map((run) => (
                  <TableRow key={run.id}>
                    <TableCell>
                      <Badge tone={run.status === "failed" ? "closed" : "open"}>{run.status}</Badge>
                    </TableCell>
                    <TableCell>{run.started_at ? new Date(run.started_at).toLocaleString() : "Pendiente"}</TableCell>
                    <TableCell>{run.items_found}</TableCell>
                    <TableCell>{run.items_created}</TableCell>
                    <TableCell>{run.items_updated}</TableCell>
                    <TableCell>{run.items_failed}</TableCell>
                    <TableCell className="min-w-64 text-xs text-slate-600 dark:text-slate-400">
                      {run.error_message ? (
                        <span className="inline-flex items-center gap-1 text-destructive">
                          <FileWarning className="h-3 w-3" />
                          {run.error_message}
                        </span>
                      ) : (
                        JSON.stringify(run.logs).slice(0, 120)
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </section>
  );
}
