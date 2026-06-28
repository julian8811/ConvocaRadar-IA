/**
 * PR B-2 (dashboard-redesign): Pipeline zone — the lists lane.
 *
 * Renders 3 widgets (each in its own Card):
 *   1. Top compatibilidad — table with Razones column (uses OpportunityRow with showReasons)
 *   2. Cierran pronto — table with Cierra en countdown column (uses OpportunityRow with showCountdown)
 *   3. Mi cola de revisión — review-queue table with En revisión badge (uses OpportunityRow with showStatusBadge)
 *
 * Each widget is independent. The empty state is rendered when the
 * corresponding slice is empty.
 */
"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { CalendarClock, ListChecks, TrendingUp } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/state";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { PipelineOpportunityItem, PipelineRead, TriageRead } from "@/lib/types";
import { OpportunityRow } from "@/components/dashboard/OpportunityRow";
import { PipelineSkeleton } from "@/components/dashboard/skeletons/PipelineSkeleton";

function TopScoredTable({ items }: { items: PipelineOpportunityItem[] }) {
  if (items.length === 0) {
    return (
      <EmptyState
        title="Sin scores todavía"
        detail="Completa tu perfil institucional y espera el cálculo automático de compatibilidad."
      />
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Convocatoria</TableHead>
          <TableHead>País</TableHead>
          <TableHead>Score</TableHead>
          <TableHead>Razones</TableHead>
          <TableHead>Monto</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <OpportunityRow key={item.id} item={item} showReasons />
        ))}
      </TableBody>
    </Table>
  );
}

function ClosingSoonTable({ items }: { items: PipelineOpportunityItem[] }) {
  if (items.length === 0) {
    return <EmptyState title="Sin cierres próximos" detail="No hay convocatorias con cierre cercano en este momento." />;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Convocatoria</TableHead>
          <TableHead>País</TableHead>
          <TableHead>Score</TableHead>
          <TableHead>Cierra en</TableHead>
          <TableHead>Monto</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <OpportunityRow key={item.id} item={item} showCountdown />
        ))}
      </TableBody>
    </Table>
  );
}

function ReviewQueueTable({ items }: { items: PipelineOpportunityItem[] }) {
  if (items.length === 0) {
    return (
      <EmptyState
        title="No tenés items en revisión"
        detail="Marcá una oportunidad como En revisión desde su detalle para empezar tu cola."
      />
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Convocatoria</TableHead>
          <TableHead>País</TableHead>
          <TableHead>Score</TableHead>
          <TableHead>Cierra en</TableHead>
          <TableHead>Monto</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <OpportunityRow key={item.id} item={item} showStatusBadge showCountdown />
        ))}
      </TableBody>
    </Table>
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

  const topScored = pipelineQuery.data?.top_scored ?? [];
  const closingSoon = pipelineQuery.data?.closing_soon ?? [];
  const reviewQueue = (triageQuery.data?.review_queue ?? []).map((item) => ({
    ...item,
    reasons: [],
  }));

  return (
    <div className="space-y-4" data-zone="pipeline">
      <Card>
        <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
          <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
            <TrendingUp className="h-4 w-4" />
            Top compatibilidad
          </CardTitle>
          <CardDescription>
            Convocatorias con mejor score y las razones que lo explican.
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <TopScoredTable items={topScored} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
          <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
            <CalendarClock className="h-4 w-4" />
            Cierran pronto
          </CardTitle>
          <CardDescription>
            Convocatorias con fecha de cierre cercana.
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <ClosingSoonTable items={closingSoon} />
        </CardContent>
      </Card>

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
        <CardContent className="overflow-x-auto p-0">
          <ReviewQueueTable items={reviewQueue as PipelineOpportunityItem[]} />
        </CardContent>
      </Card>
    </div>
  );
}
