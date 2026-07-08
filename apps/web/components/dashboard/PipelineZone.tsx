/**
 * PR B-2 (dashboard-redesign): Pipeline zone — the lists lane.
 *
 * Renders 2 widgets (each in its own Card):
 *   1. Top compatibilidad — cards with score badge and reasons
 *   2. Mi cola de revisión — cards with review badge and countdown
 *
 * Cierran pronto was removed since Próximos cierres (7 días) in TriageZone
 * already covers the same data with a tighter window.
 */
"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Clock, Globe, ListChecks } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { PipelineOpportunityItem, PipelineRead, TriageRead } from "@/lib/types";
import { PipelineSkeleton } from "@/components/dashboard/skeletons/PipelineSkeleton";

function formatNumber(value: number) {
  return new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 }).format(value);
}

function ClosingSoonGrid({ items }: { items: PipelineOpportunityItem[] }) {
  if (items.length === 0) {
    return (
      <CardContent className="p-6">
        <EmptyState title="Sin cierres próximos" detail="No hay convocatorias con cierre cercano en este momento." />
      </CardContent>
    );
  }
  return (
    <CardContent className="grid gap-4 p-4 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => {
        const urgency = item.days_to_close !== null && item.days_to_close <= 3 ? "urgent" : item.days_to_close !== null && item.days_to_close <= 7 ? "soon" : "normal";
        const borderColor = urgency === "urgent" ? "border-l-rose-500" : urgency === "soon" ? "border-l-amber-500" : "border-l-sky-500";
        const daysText = item.days_to_close === 0 ? "Hoy" : item.days_to_close === 1 ? "1 día" : `${item.days_to_close} días`;
        return (
          <Link key={item.id} href={`/opportunities/${item.id}`} className="group block">
            <div className={`rounded-lg border border-slate-200 bg-white p-4 transition-all hover:shadow-md dark:border-slate-700 dark:bg-slate-900 border-l-4 ${borderColor}`}>
              <p className="line-clamp-2 text-sm font-medium text-slate-950 group-hover:text-cyan-700 dark:text-white dark:group-hover:text-cyan-300">
                {item.title}
              </p>
              <div className="mt-2 flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
                <span className="flex items-center gap-1">
                  <Globe className="h-3 w-3" />
                  {item.country || "—"}
                </span>
                {item.score !== null && <span>Score: {Math.round(item.score)}</span>}
              </div>
              <div className="mt-3 flex items-center justify-between">
                <Badge tone={urgency === "urgent" ? "destructive" : urgency === "soon" ? "medium" : "muted"}>
                  <Clock className="mr-1 h-3 w-3" />
                  {daysText}
                </Badge>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {item.funding_amount !== null ? `${formatNumber(item.funding_amount)}${item.currency ? ` ${item.currency}` : ""}` : "—"}
                </span>
              </div>
            </div>
          </Link>
        );
      })}
    </CardContent>
  );
}

function ReviewQueueGrid({ items }: { items: PipelineOpportunityItem[] }) {
  if (items.length === 0) {
    return (
      <CardContent className="p-6">
        <EmptyState
          title="No tenés items en revisión"
          detail="Marcá una oportunidad como En revisión desde su detalle para empezar tu cola."
        />
      </CardContent>
    );
  }
  return (
    <CardContent className="grid gap-4 p-4 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => {
        const daysText = item.days_to_close === 0 ? "Hoy" : item.days_to_close === 1 ? "1 día" : item.days_to_close !== null ? `${item.days_to_close} días` : "—";
        return (
          <Link key={item.id} href={`/opportunities/${item.id}`} className="group block">
            <div className="rounded-lg border border-sky-200 bg-white p-4 transition-all hover:shadow-md dark:border-sky-800 dark:bg-slate-900">
              <div className="flex items-start justify-between gap-2">
                <p className="flex-1 line-clamp-2 text-sm font-medium text-slate-950 group-hover:text-cyan-700 dark:text-white dark:group-hover:text-cyan-300">
                  {item.title}
                </p>
                <Badge tone="review">Revisión</Badge>
              </div>
              <div className="mt-2 flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
                <span className="flex items-center gap-1">
                  <Globe className="h-3 w-3" />
                  {item.country || "—"}
                </span>
                {item.score !== null && <span>Score: {Math.round(item.score)}</span>}
                {item.days_to_close !== null && (
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {daysText}
                  </span>
                )}
              </div>
              <span className="mt-2 block text-xs text-slate-500 dark:text-slate-400">
                {item.funding_amount !== null ? `${formatNumber(item.funding_amount)}${item.currency ? ` ${item.currency}` : ""}` : "—"}
              </span>
            </div>
          </Link>
        );
      })}
    </CardContent>
  );
}

export function PipelineZone() {
  const pipelineQuery = useQuery<PipelineRead>({
    queryKey: ["dashboard-pipeline"],
    queryFn: api.dashboardPipeline,
    placeholderData: keepPreviousData,
  });

  // The review queue is a slice of /dashboard/triage (not /dashboard/pipeline).
  // The backend exposes it there because it's tied to the user's user_status
  // and we want a single round trip for the hero lane.
  const triageQuery = useQuery<TriageRead>({
    queryKey: ["dashboard-triage"],
    queryFn: api.dashboardTriage,
    placeholderData: keepPreviousData,
  });

  if (pipelineQuery.isLoading && triageQuery.isLoading) return <PipelineSkeleton />;
  if (pipelineQuery.error) return <ErrorState message={pipelineQuery.error.message} />;

  const reviewQueue = (triageQuery.data?.review_queue ?? []).map((item) => ({
    ...item,
    reasons: [],
  }));

  return (
    <div className="space-y-4" data-zone="pipeline">
      <Card>
        <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
          <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
            <ListChecks className="h-4 w-4" />
            Mi cola de revisión
          </CardTitle>
          <CardDescription>
            Items que marcaste como En revisión o Mantener.
          </CardDescription>
        </CardHeader>
        <ReviewQueueGrid items={reviewQueue as PipelineOpportunityItem[]} />
      </Card>
    </div>
  );
}
