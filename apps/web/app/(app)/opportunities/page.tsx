"use client";

import { ChevronLeft, ChevronRight, Download, Eye, Filter, Search, Star } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, downloadReport } from "@/lib/api";
import { decodeVisibleText, isNoiseVisibleText } from "@/lib/text";
import type { Opportunity, Source } from "@/lib/types";

const statuses = [
  { value: "open", label: "Abiertas" },
  { value: "closing_soon", label: "Cierran pronto" },
  { value: "closed", label: "Cerradas" },
  { value: "unknown", label: "Sin fecha" },
];

const statusOrder: Record<string, number> = {
  open: 0,
  closing_soon: 1,
  unknown: 2,
  closed: 3,
};

function sourceName(item: Opportunity, sources: Source[]) {
  return sources.find((source) => source.id === item.source_id)?.name ?? "Fuente no identificada";
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

function formatAmount(value: string | null) {
  if (!value) return "Por validar";
  const trimmed = value.trim();
  if (!trimmed) return "Por validar";
  if (
    trimmed.length > 90 ||
    trimmed.startsWith("{") ||
    trimmed.startsWith("[") ||
    trimmed.includes('"budgetYearsColumns"') ||
    trimmed.includes('"plannedOpeningDate"') ||
    trimmed.includes('"deadlineDate"')
  ) {
    return "Por validar";
  }
  return trimmed;
}

function cleanSummary(value: string | null | undefined) {
  const text = decodeVisibleText(value, "Sin resumen.");
  if (/color: white|\.box-address|\.caja|display: flex|justify-content: center|font-weight: bold|text-decoration: underline/i.test(text)) {
    return "Sin resumen.";
  }
  return text;
}

function sortItems(items: Opportunity[]) {
  return [...items].sort((a, b) => {
    const statusDiff = (statusOrder[a.status] ?? 99) - (statusOrder[b.status] ?? 99);
    if (statusDiff !== 0) return statusDiff;
    const aDate = a.close_date ? new Date(a.close_date).getTime() : Number.POSITIVE_INFINITY;
    const bDate = b.close_date ? new Date(b.close_date).getTime() : Number.POSITIVE_INFINITY;
    if (aDate !== bDate) return aDate - bDate;
    return a.title.localeCompare(b.title, "es");
  });
}

function initialSemanticQuery() {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("semantic") ?? "";
}

export default function OpportunitiesPage() {
  const [search, setSearch] = useState("");
  const [semanticQuery, setSemanticQuery] = useState(initialSemanticQuery);
  const [searchMode, setSearchMode] = useState<"text" | "semantic">(() => (initialSemanticQuery() ? "semantic" : "text"));
  const [status, setStatus] = useState("open");
  const [country, setCountry] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const queryClient = useQueryClient();

  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (status) params.set("status", status);
    if (country) params.set("country", country);
    if (category) params.set("category", category);
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    const queryString = params.toString();
    return queryString ? `?${queryString}` : "";
  }, [category, country, page, search, status]);

  const opportunities = useQuery({ queryKey: ["opportunities", query], queryFn: () => api.opportunities(query) });
  const semanticResults = useQuery({
    queryKey: ["semantic-search", semanticQuery],
    queryFn: () => api.semanticSearch(semanticQuery),
    enabled: searchMode === "semantic" && semanticQuery.trim().length >= 3,
  });
  const actionLinkClass =
    "inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-300 bg-white text-slate-900 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800";

  const favorite = useMutation({
    mutationFn: api.favorite,
    onSuccess: () => {
      toast.success("Convocatoria guardada");
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
    },
  });

  const createCsv = useMutation({
    mutationFn: () =>
      api.createReport({
        title: "Exportación CSV de convocatorias",
        format: "csv",
        filters: { search, status, country, category },
      }),
    onSuccess: async (report) => {
      toast.success("CSV generado");
      await downloadReport(report);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo exportar CSV"),
  });

  const sourceItems = sources.data ?? [];
  const semanticItems = useMemo(
    () => (semanticResults.data?.items ?? []).map((item) => item.opportunity).filter((item) => !isNoiseVisibleText(item.title)),
    [semanticResults.data?.items],
  );
  const items = useMemo(() => {
    // Server-side handles all filtering (noise, status, search) via
    // build_opportunity_query. Client-side filtering broke pagination
    // because items.length no longer matched the server's page slice.
    if (searchMode === "semantic" && semanticQuery.trim().length >= 3) {
      return sortItems(semanticItems);
    }
    return sortItems(opportunities.data?.items ?? []);
  }, [opportunities.data?.items, semanticItems, searchMode, semanticQuery]);
  const total = searchMode === "semantic" ? opportunities.data?.total ?? 0 : (opportunities.data?.total ?? 0);
  const totalPages = Math.max(Math.ceil(total / pageSize), 1);
  const openCount = items.filter((item) => item.status === "open").length;
  const closingSoon = items.filter((item) => item.status === "closing_soon").length;
  const withSource = items.filter((item) => Boolean(item.source_id)).length;
  const favorites = items.filter((item) => item.is_favorite).length;

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Oportunidades activas</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            Monitoreo de convocatorias reales con fuente, entidad, país, cierre, monto y prioridad visible.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" type="button">
            <Filter className="h-4 w-4" />
            Filtros avanzados
          </Button>
          <Button variant="outline" onClick={() => createCsv.mutate()} disabled={createCsv.isPending}>
            <Download className="h-4 w-4" />
            {createCsv.isPending ? "Exportando..." : "Exportar CSV"}
          </Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <QuickStat label="Total" value={total} detail="Convocatorias detectadas" tone="high" />
        <QuickStat label="Abiertas hoy" value={openCount} detail="Vigentes hoy" tone="open" />
        <QuickStat label="Cierran pronto" value={closingSoon} detail="Requieren seguimiento" tone="closing_soon" />
        <QuickStat label="Con fuente" value={withSource} detail={`${favorites} favoritas`} tone="medium" />
      </div>

      <Card>
        <CardContent className="grid gap-3 p-4 xl:grid-cols-[auto_1.35fr_0.8fr_0.8fr_0.8fr_auto]">
          <Select
            value={searchMode}
            onChange={(event) => {
              setSearchMode(event.target.value as "text" | "semantic");
              setPage(1);
            }}
          >
            <option value="text">Texto</option>
            <option value="semantic">Semántica</option>
          </Select>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <Input
              className="h-10 pl-9"
              placeholder={searchMode === "semantic" ? "Ej: innovación en salud con fondos europeos" : "Buscar por título o entidad"}
              value={searchMode === "semantic" ? semanticQuery : search}
              onChange={(event) => {
                if (searchMode === "semantic") {
                  setSemanticQuery(event.target.value);
                } else {
                  setSearch(event.target.value);
                }
                setPage(1);
              }}
            />
          </div>
          <Select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
          >
            {statuses.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </Select>
          <Input
            placeholder="País"
            value={country}
            onChange={(event) => {
              setCountry(event.target.value);
              setPage(1);
            }}
          />
          <Input
            placeholder="Categoría"
            value={category}
            onChange={(event) => {
              setCategory(event.target.value);
              setPage(1);
            }}
          />
          <Button variant="outline" onClick={() => createCsv.mutate()} disabled={createCsv.isPending}>
            <Download className="h-4 w-4" />
            CSV
          </Button>
        </CardContent>
      </Card>

      {opportunities.isLoading || sources.isLoading || (searchMode === "semantic" && semanticResults.isLoading) ? (
        <LoadingState label="Cargando convocatorias" />
      ) : null}
      {opportunities.error ? <ErrorState message={opportunities.error.message} /> : null}
      {semanticResults.error ? <ErrorState message={semanticResults.error.message} /> : null}
      {sources.error ? <ErrorState message={sources.error.message} /> : null}
      {opportunities.data && items.length === 0 ? (
        <EmptyState
          title="No hay convocatorias"
          detail={
            searchMode === "semantic"
              ? "Prueba otra consulta semántica o ejecuta fuentes desde el panel de Fuentes."
              : "Ejecuta una fuente o revisa los filtros activos."
          }
        />
      ) : null}

      {opportunities.data && items.length > 0 ? (
        <Card>
          <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
            <CardTitle className="text-lg text-slate-950 dark:text-white">
              {total} oportunidades detectadas - página {page} de {totalPages}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 overflow-x-auto p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Título</TableHead>
                  <TableHead>Fuente</TableHead>
                  <TableHead>Entidad</TableHead>
                  <TableHead>País</TableHead>
                  <TableHead>Categoría</TableHead>
                  <TableHead>Cierre</TableHead>
                  <TableHead>Monto</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Acciones</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="min-w-72 max-w-[24rem] font-medium text-slate-950 dark:text-white">
                      <Link href={`/opportunities/${item.id}`} className="block hover:underline">
                        <span
                          className="block max-h-12 overflow-hidden"
                          style={{ display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2 }}
                        >
                          {decodeVisibleText(item.title, "Convocatoria sin título")}
                        </span>
                      </Link>
                      <p
                        className="mt-1 max-h-10 overflow-hidden text-xs text-slate-500 dark:text-slate-400"
                        style={{ display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2 }}
                      >
                        {cleanSummary(item.summary)}
                      </p>
                      {item.summary && item.summary.length > 100 ? (
                        <details className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                          <summary className="cursor-pointer text-cyan-700 dark:text-cyan-200/80 hover:underline">
                            Ver resumen completo
                          </summary>
                          <p className="mt-1 leading-5 text-slate-700 dark:text-slate-300">{cleanSummary(item.summary)}</p>
                        </details>
                      ) : null}
                      <p className="mt-2 text-[11px] uppercase tracking-[0.16em] text-cyan-700 dark:text-cyan-200/80">
                        Fuente: {decodeVisibleText(sourceName(item, sourceItems), "Fuente no identificada")}
                      </p>
                    </TableCell>
                    <TableCell className="max-w-48">
                      <span className="block truncate text-sm text-slate-700 dark:text-slate-200">
                        {decodeVisibleText(sourceName(item, sourceItems), "Fuente no identificada")}
                      </span>
                    </TableCell>
                    <TableCell>{decodeVisibleText(item.entity, "Sin entidad")}</TableCell>
                    <TableCell>{decodeVisibleText(item.country, "Sin país")}</TableCell>
                    <TableCell className="max-w-40">
                      <span className="block truncate">{decodeVisibleText(item.categories.slice(0, 2).join(", "), "Sin categoría")}</span>
                    </TableCell>
                    <TableCell>{item.close_date ? new Date(item.close_date).toLocaleDateString("es-CO") : "Sin fecha"}</TableCell>
                    <TableCell className="max-w-56 break-words text-slate-700 dark:text-slate-200">{formatAmount(item.funding_amount_raw)}</TableCell>
                    <TableCell>
                      <Badge tone={item.status}>{translateOpportunityStatus(item.status)}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button variant="outline" size="icon" title="Guardar" onClick={() => favorite.mutate(item.id)}>
                          <Star className="h-4 w-4" />
                        </Button>
                        <Link href={`/opportunities/${item.id}`} className={actionLinkClass} aria-label="Ver convocatoria">
                          <Eye className="h-4 w-4" />
                        </Link>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="flex items-center justify-between gap-3 px-4 pb-4 pt-2">
              <Button variant="outline" disabled={page <= 1} onClick={() => setPage((current) => Math.max(current - 1, 1))}>
                <ChevronLeft className="h-4 w-4" />
                Anterior
              </Button>
              <span className="text-sm text-slate-500 dark:text-slate-400">
                Mostrando {items.length} de {total}
              </span>
              <Button variant="outline" disabled={page >= totalPages} onClick={() => setPage((current) => Math.min(current + 1, totalPages))}>
                Siguiente
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </section>
  );
}

function QuickStat({ label, value, detail, tone }: { label: string; value: number; detail: string; tone: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{label}</p>
            <p className="mt-1 text-2xl font-semibold text-slate-950 dark:text-white">{value}</p>
            <p className="text-sm text-slate-500 dark:text-slate-400">{detail}</p>
          </div>
          <Badge tone={tone}>{label}</Badge>
        </div>
      </CardContent>
    </Card>
  );
}
