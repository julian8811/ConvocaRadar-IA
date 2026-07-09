"use client";

import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Download, Eye, Search, Star, Trash2 } from "lucide-react";
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
import { api, API_URL, TOKEN_COOKIE_NAME } from "@/lib/api";
import { decodeVisibleText, isNoiseVisibleText } from "@/lib/text";
import type { Opportunity, Source } from "@/lib/types";

const statuses = [
  { value: "", label: "Todos los estados" },
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
  if (trimmed.length > 90 || trimmed.startsWith("{") || trimmed.startsWith("[")) return "Por validar";
  return trimmed;
}

function cleanSummary(value: string | null | undefined) {
  const text = decodeVisibleText(value, "Sin resumen.");
  if (/color: white|\.box-address|display: flex/i.test(text)) return "Sin resumen.";
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

export default function OpportunitiesPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("open");
  const [country, setCountry] = useState("");
  const [category, setCategory] = useState("");
  const [closeDateFrom, setCloseDateFrom] = useState("");
  const [closeDateTo, setCloseDateTo] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const pageSize = 10;
  const queryClient = useQueryClient();
  const actionLinkClass =
    "inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-300 bg-white text-slate-900 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800";

  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (status) params.set("status", status);
    if (country) params.set("country", country);
    if (category) params.set("category", category);
    if (closeDateFrom) params.set("close_date_from", closeDateFrom);
    if (closeDateTo) params.set("close_date_to", closeDateTo);
    if (minAmount) params.set("min_amount", minAmount);
    if (maxAmount) params.set("max_amount", maxAmount);
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    return params.toString() ? `?${params.toString()}` : "";
  }, [search, status, country, category, closeDateFrom, closeDateTo, minAmount, maxAmount, page]);

  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const opportunities = useQuery({ queryKey: ["opportunities", query], queryFn: () => api.opportunities(query) });

  const favorite = useMutation({
    mutationFn: api.favorite,
    onSuccess: () => { toast.success("Guardada"); queryClient.invalidateQueries({ queryKey: ["opportunities"] }); },
  });

  const setStatusBatch = useMutation({
    mutationFn: async (status: string) => {
      const token = document.cookie.split("; ").find((r) => r.startsWith("convocaradar_token="))?.split("=")[1];
      const results = await Promise.allSettled(
        Array.from(selected).map((id) =>
          fetch(`${API_URL}/opportunities/${id}/status?status=${status}`, {
            method: "POST", headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
            credentials: "include",
          })
        )
      );
      return { total: selected.size, done: results.filter((r) => r.status === "fulfilled").length };
    },
    onSuccess: (r) => { toast.success(`${r.done} de ${r.total} actualizadas`); setSelected(new Set()); queryClient.invalidateQueries({ queryKey: ["opportunities"] }); },
    onError: () => toast.error("Error al actualizar"),
  });

  const exportSelected = useMutation({
    mutationFn: async () => {
      const token = document.cookie.split("; ").find((r) => r.startsWith("convocaradar_token="))?.split("=")[1];
      const allSelected = Array.from(selected);
      const csvHeader = "title,entity,country,status,close_date,funding_amount,official_url\n";
      const rows = items.filter((i) => selected.has(i.id)).map((i) =>
        `"${i.title}","${i.entity}","${i.country}","${i.status}",${i.close_date ?? ""},${i.funding_amount_raw ?? ""},"${i.official_url ?? ""}"`
      ).join("\n");
      const blob = new Blob([csvHeader + rows], { type: "text/csv" });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "convocatorias-seleccionadas.csv";
      a.click(); window.URL.revokeObjectURL(url);
    },
  });

  const items = useMemo(() => sortItems(opportunities.data?.items ?? []), [opportunities.data?.items]);
  const total = opportunities.data?.total ?? 0;
  const totalPages = Math.max(Math.ceil(total / pageSize), 1);

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Convocatorias</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">{total} oportunidades detectadas</p>
        </div>
      </div>

      <Card>
        <CardContent className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-5">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            {statuses.map((s) => (<option key={s.value} value={s.value}>{s.label}</option>))}
          </Select>
          <Input placeholder="Buscar..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          <Input placeholder="País" value={country} onChange={(e) => { setCountry(e.target.value); setPage(1); }} />
          <Input placeholder="Categoría" value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }} />
          <Button variant="outline" onClick={() => setShowAdvanced(!showAdvanced)}>
            {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            Filtros avanzados
          </Button>
        </CardContent>
        {showAdvanced && (
          <CardContent className="grid gap-3 border-t border-slate-200 p-4 sm:grid-cols-2 xl:grid-cols-4 dark:border-slate-700">
            <div>
              <label className="text-xs text-slate-500 dark:text-slate-400">Cierre desde</label>
              <Input type="date" value={closeDateFrom} onChange={(e) => { setCloseDateFrom(e.target.value); setPage(1); }} />
            </div>
            <div>
              <label className="text-xs text-slate-500 dark:text-slate-400">Cierre hasta</label>
              <Input type="date" value={closeDateTo} onChange={(e) => { setCloseDateTo(e.target.value); setPage(1); }} />
            </div>
            <div>
              <label className="text-xs text-slate-500 dark:text-slate-400">Monto mínimo (USD)</label>
              <Input type="number" placeholder="Ej: 50000" value={minAmount} onChange={(e) => { setMinAmount(e.target.value); setPage(1); }} />
            </div>
            <div>
              <label className="text-xs text-slate-500 dark:text-slate-400">Monto máximo (USD)</label>
              <Input type="number" placeholder="Ej: 500000" value={maxAmount} onChange={(e) => { setMaxAmount(e.target.value); setPage(1); }} />
            </div>
          </CardContent>
        )}
      </Card>

      {/* Batch actions bar */}
      {selected.size > 0 && (
        <Card className="border-cyan-500/30 bg-cyan-50/50 dark:bg-cyan-400/5 dark:border-cyan-400/20">
          <CardContent className="flex flex-wrap items-center gap-3 p-3">
            <span className="text-sm font-medium text-cyan-800 dark:text-cyan-200">{selected.size} seleccionadas</span>
            <Button size="sm" variant="outline" onClick={() => setStatusBatch.mutate("review")}>
              <Eye className="h-3.5 w-3.5" /> Marcar revisadas
            </Button>
            <Button size="sm" variant="outline" onClick={() => exportSelected.mutate()}>
              <Download className="h-3.5 w-3.5" /> Exportar selección
            </Button>
            <Button size="sm" variant="outline" onClick={() => setSelected(new Set())}>
              <Trash2 className="h-3.5 w-3.5" /> Limpiar
            </Button>
          </CardContent>
        </Card>
      )}

      {opportunities.isLoading ? <LoadingState label="Cargando" /> : null}
      {opportunities.error ? <ErrorState message={opportunities.error.message} /> : null}
      {opportunities.data && items.length === 0 ? (
        <EmptyState title="Sin resultados" detail="Probá con otros filtros." />
      ) : null}

      {opportunities.data && items.length > 0 ? (
        <Card>
          <CardContent className="space-y-4 overflow-x-auto p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-cyan-600"
                      checked={items.length > 0 && selected.size === items.length}
                      onChange={(e) => setSelected(e.target.checked ? new Set(items.map((i) => i.id)) : new Set())}
                    />
                  </TableHead>
                  <TableHead>Título</TableHead>
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
                  <TableRow key={item.id} className={selected.has(item.id) ? "bg-cyan-50/50 dark:bg-cyan-400/5" : ""}>
                    <TableCell>
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-cyan-600"
                        checked={selected.has(item.id)}
                        onChange={() => {
                          const next = new Set(selected);
                          next.has(item.id) ? next.delete(item.id) : next.add(item.id);
                          setSelected(next);
                        }}
                      />
                    </TableCell>
                    <TableCell className="min-w-64 max-w-[20rem] font-medium text-slate-950 dark:text-white">
                      <Link href={`/opportunities/${item.id}`} className="hover:underline">
                        <span className="line-clamp-2">{decodeVisibleText(item.title, "Sin título")}</span>
                      </Link>
                      <p className="mt-1 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">{cleanSummary(item.summary)}</p>
                    </TableCell>
                    <TableCell>{decodeVisibleText(item.country, "—")}</TableCell>
                    <TableCell className="max-w-32">
                      <span className="truncate block">{item.categories.slice(0, 2).join(", ") || "—"}</span>
                    </TableCell>
                    <TableCell>{item.close_date ? new Date(item.close_date).toLocaleDateString("es-CO") : "Sin fecha"}</TableCell>
                    <TableCell>{formatAmount(item.funding_amount_raw)}</TableCell>
                    <TableCell><Badge tone={item.status}>{translateOpportunityStatus(item.status)}</Badge></TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button variant="outline" size="icon" title="Favorita" onClick={() => favorite.mutate(item.id)}>
                          <Star className="h-4 w-4" />
                        </Button>
                        <Link href={`/opportunities/${item.id}`} className={actionLinkClass} aria-label="Ver">
                          <Eye className="h-4 w-4" />
                        </Link>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="flex items-center justify-between gap-3 px-4 pb-4 pt-2">
              <Button variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                <ChevronLeft className="h-4 w-4" /> Anterior
              </Button>
              <span className="text-sm text-slate-500">Pág. {page} de {totalPages} ({total} total)</span>
              <Button variant="outline" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
                Siguiente <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </section>
  );
}
