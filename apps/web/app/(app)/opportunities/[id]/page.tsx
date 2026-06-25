"use client";

import {
  ArrowLeft,
  Download,
  ExternalLink,
  FileCheck,
  Gauge,
  Paperclip,
  ShieldAlert,
  Sparkles,
  Star,
  Trash2,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ElementType, FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { api, downloadOpportunityDocument, uploadOpportunityDocument } from "@/lib/api";
import { decodeVisibleText } from "@/lib/text";
import type { OpportunityDocument } from "@/lib/types";

const workflowStatuses = ["review", "apply", "discarded", "submitted", "won", "lost"];
const workflowLabels: Record<string, string> = {
  review: "Revisar",
  apply: "Aplicar",
  discarded: "Descartada",
  submitted: "Enviada",
  won: "Ganada",
  lost: "Perdida",
};

function statusLabel(status: string) {
  const map: Record<string, string> = {
    open: "Abierta",
    closed: "Cerrada",
    closing_soon: "Por cerrar",
    unknown: "Sin validar",
  };
  return map[status] ?? status;
}

function isValidExternalUrl(value: string | null | undefined) {
  if (!value) return false;
  try {
    const parsed = new URL(value);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && parsed.hostname.length > 0;
  } catch {
    return false;
  }
}

function isNoiseTitle(title: string) {
  const normalized = title
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/&#x([0-9a-fA-F]+);/g, (_, code) => String.fromCharCode(Number.parseInt(code, 16)))
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
  return normalized.includes("@") || normalized.toLowerCase().startsWith("http://") || normalized.toLowerCase().startsWith("https://");
}

export default function OpportunityDetailPage() {
  const params = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const opportunity = useQuery({
    queryKey: ["opportunity", params.id],
    queryFn: () => api.opportunity(params.id),
  });
  const scores = useQuery({
    queryKey: ["opportunity-scores", params.id],
    queryFn: () => api.scores(params.id),
  });
  const documents = useQuery({
    queryKey: ["opportunity-documents", params.id],
    queryFn: () => api.opportunityDocuments(params.id),
  });

  const calculateScore = useMutation({
    mutationFn: () => api.score(params.id),
    onSuccess: () => {
      toast.success("Compatibilidad recalculada");
      queryClient.invalidateQueries({ queryKey: ["opportunity-scores", params.id] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo calcular la compatibilidad"),
  });

  const updateStatus = useMutation({
    mutationFn: (status: string) => api.setOpportunityStatus(params.id, status),
    onSuccess: () => {
      toast.success("Estado actualizado");
      queryClient.invalidateQueries({ queryKey: ["opportunity", params.id] });
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo actualizar el estado"),
  });

  const toggleFavorite = useMutation({
    mutationFn: () => {
      const current = opportunity.data?.is_favorite ?? false;
      return current ? api.unfavorite(params.id) : api.favorite(params.id);
    },
    onSuccess: () => {
      toast.success("Seguimiento actualizado");
      queryClient.invalidateQueries({ queryKey: ["opportunity", params.id] });
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo actualizar el seguimiento"),
  });

  const uploadDocument = useMutation({
    mutationFn: (file: File) => uploadOpportunityDocument(params.id, file),
    onSuccess: () => {
      toast.success("Documento cargado");
      queryClient.invalidateQueries({ queryKey: ["opportunity-documents", params.id] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo cargar el documento"),
  });

  const deleteDocument = useMutation({
    mutationFn: (documentId: string) => api.deleteOpportunityDocument(documentId),
    onSuccess: () => {
      toast.success("Documento eliminado");
      queryClient.invalidateQueries({ queryKey: ["opportunity-documents", params.id] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo eliminar el documento"),
  });

  const downloadDocument = useMutation({
    mutationFn: downloadOpportunityDocument,
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo descargar el documento"),
  });

  function submitDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    if (file instanceof File && file.size > 0) {
      uploadDocument.mutate(file);
      event.currentTarget.reset();
    }
  }

  if (opportunity.isLoading) return <LoadingState label="Cargando detalle" />;
  if (opportunity.error) return <ErrorState message={opportunity.error.message} />;

  const item = opportunity.data;
  const latestScore = scores.data?.[0];

  if (!item) return null;
  if (isNoiseTitle(item.title)) {
    return <ErrorState message="Esta convocatoria parece ser ruido del scraping y no tiene una ficha válida." />;
  }
  const officialUrl = item.official_url && isValidExternalUrl(item.official_url) ? item.official_url : null;
  const applicationUrl = item.application_url && isValidExternalUrl(item.application_url) ? item.application_url : null;

  return (
    <section className="space-y-6">
      <Link href="/opportunities" className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-cyan-700 dark:text-slate-400 dark:hover:text-cyan-200">
        <ArrowLeft className="h-4 w-4" />
        Volver a convocatorias
      </Link>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="mb-3 flex flex-wrap gap-2">
            <Badge tone={item.status}>{statusLabel(item.status)}</Badge>
            {item.categories.map((category) => (
              <Badge key={category} tone="medium">
                {category}
              </Badge>
            ))}
          </div>
          <h1 className="max-w-4xl text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">{decodeVisibleText(item.title, "Convocatoria sin título")}</h1>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            {item.entity} · {item.country} · Fuente: {item.source_id ? "Con fuente" : "Sin fuente"} · Cierre:{" "}
            {item.close_date ? new Date(item.close_date).toLocaleDateString("es-CO") : "Sin fecha"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant={item.is_favorite ? "default" : "outline"} onClick={() => toggleFavorite.mutate()} disabled={toggleFavorite.isPending}>
            <Star className="h-4 w-4" />
            {item.is_favorite ? "Seguimiento activo" : "Marcar seguimiento"}
          </Button>
          <Button variant="secondary" onClick={() => calculateScore.mutate()} disabled={calculateScore.isPending}>
            <Gauge className="h-4 w-4" />
            {calculateScore.isPending ? "Calculando..." : "Calcular compatibilidad"}
          </Button>
          {officialUrl ? (
            <Button variant="outline" onClick={() => window.open(officialUrl, "_blank", "noopener,noreferrer")}>
              <ExternalLink className="h-4 w-4" />
              Ir a la fuente oficial
            </Button>
          ) : applicationUrl ? (
            <Button variant="outline" onClick={() => window.open(applicationUrl, "_blank", "noopener,noreferrer")}>
              <ExternalLink className="h-4 w-4" />
              Ir a la postulaci?n
            </Button>
          ) : (
            <Button variant="outline" disabled title="No hay una URL oficial confirmada para esta convocatoria">
              <ExternalLink className="h-4 w-4" />
              Enlace no disponible
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
              <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
                <Sparkles className="h-4 w-4" />
                Resumen de IA
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-5 text-sm leading-6 text-slate-700 dark:text-slate-300">
              {decodeVisibleText(item.summary, "Sin resumen disponible.")}
            </CardContent>
          </Card>

          <InfoList title="Requisitos" icon={FileCheck} items={item.requirements} empty="No se han identificado requisitos." />
          <InfoList title="Documentos requeridos" icon={FileCheck} items={item.documents_required} empty="No se han identificado documentos." />

          <DocumentsCard
            documents={documents.data ?? []}
            isLoading={documents.isLoading}
            onSubmit={submitDocument}
            onDownload={(document) => downloadDocument.mutate(document)}
            onDelete={(documentId) => deleteDocument.mutate(documentId)}
            isUploading={uploadDocument.isPending}
            isDeleting={deleteDocument.isPending}
            isDownloading={downloadDocument.isPending}
          />
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
              <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
                <Gauge className="h-4 w-4" />
                Compatibilidad
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 pt-5 text-sm">
              {scores.isLoading ? (
                <p className="text-slate-500 dark:text-slate-400">Cargando compatibilidad...</p>
              ) : latestScore ? (
                <>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500 dark:text-slate-400">Puntaje</span>
                    <span className="text-2xl font-semibold text-slate-950 dark:text-white">{Math.round(latestScore.score)}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                    <div className="h-2 rounded-full bg-cyan-500" style={{ width: `${Math.min(latestScore.score, 100)}%` }} />
                  </div>
                  <Badge tone={latestScore.priority}>{latestScore.priority}</Badge>
                  <InfoMini title="Razones" items={latestScore.reasons} />
                  <InfoMini title="Alertas" items={latestScore.warnings} />
                </>
              ) : (
                <p className="text-slate-500 dark:text-slate-400">Aún no hay compatibilidad calculada para esta convocatoria.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
              <CardTitle className="text-slate-950 dark:text-white">Datos clave</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 pt-5 text-sm">
              <KeyValue label="Monto" value={item.funding_amount_raw ?? "Por validar"} />
              <KeyValue label="Estado interno" value={workflowLabels[item.user_status] ?? item.user_status} />
              <KeyValue label="Temas" value={item.topics.join(", ") || "Sin temas"} />              <KeyValue label="Regi?n" value={item.region ?? "Sin regi?n"} />
              <KeyValue label="Idioma" value={item.language ?? "No indicado"} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
              <CardTitle className="text-slate-950 dark:text-white">Seguimiento</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2 pt-5">
              {workflowStatuses.map((status) => (
                <Button
                  key={status}
                  variant={item.user_status === status ? "default" : "outline"}
                  size="sm"
                  disabled={updateStatus.isPending}
                  onClick={() => updateStatus.mutate(status)}
                >
                  {workflowLabels[status]}
                </Button>
              ))}
            </CardContent>
          </Card>

          <InfoList title="Riesgos" icon={ShieldAlert} items={item.risk_flags} empty="No se detectaron riesgos." />
        </div>
      </div>
    </section>
  );
}

function DocumentsCard({
  documents,
  isLoading,
  onSubmit,
  onDownload,
  onDelete,
  isUploading,
  isDeleting,
  isDownloading,
}: {
  documents: OpportunityDocument[];
  isLoading: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onDownload: (document: OpportunityDocument) => void;
  onDelete: (documentId: string) => void;
  isUploading: boolean;
  isDeleting: boolean;
  isDownloading: boolean;
}) {
  return (
    <Card>
      <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
        <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
          <Paperclip className="h-4 w-4" />
          Adjuntos
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-5">
        <form className="flex flex-col gap-2 sm:flex-row" onSubmit={onSubmit}>
          <Input name="file" type="file" accept=".pdf,.html,.txt,.docx,.xlsx" required />
          <Button disabled={isUploading}>
            <Upload className="h-4 w-4" />
            Subir
          </Button>
        </form>
        {isLoading ? <p className="text-sm text-slate-500 dark:text-slate-400">Cargando documentos...</p> : null}
        {!isLoading && documents.length === 0 ? <p className="text-sm text-slate-500 dark:text-slate-400">No hay adjuntos cargados.</p> : null}
        <div className="space-y-2">
          {documents.map((document) => (
            <div key={document.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-950 dark:text-white">{decodeVisibleText(document.file_name, "Documento")}</p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {document.file_type} · {new Date(document.created_at).toLocaleString("es-CO")}
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="icon" title="Descargar" disabled={isDownloading} onClick={() => onDownload(document)}>
                  <Download className="h-4 w-4" />
                </Button>
                <Button variant="outline" size="icon" title="Eliminar" disabled={isDeleting} onClick={() => onDelete(document.id)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-slate-200 dark:border-slate-700 pb-2">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="text-right font-medium text-slate-950 dark:text-white">{value}</span>
    </div>
  );
}

function InfoMini({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <p className="mb-2 text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{title}</p>
      <ul className="space-y-1 text-slate-700 dark:text-slate-300">
        {items.map((item) => (
          <li key={item}>- {item}</li>
        ))}
      </ul>
    </div>
  );
}

function InfoList({ title, icon: Icon, items, empty }: { title: string; icon: ElementType; items: string[]; empty: string }) {
  return (
    <Card>
      <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
        <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
          <Icon className="h-4 w-4" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-5">
        {items.length ? (
          <ul className="space-y-2 text-sm text-slate-700 dark:text-slate-300">
            {items.map((item) => (
              <li key={item} className="rounded-lg bg-slate-100 px-3 py-2 dark:bg-slate-800">
                {item}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}
