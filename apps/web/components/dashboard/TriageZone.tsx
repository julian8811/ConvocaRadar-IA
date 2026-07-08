/**
 * PR B-2 (dashboard-redesign): Triage zone — the "Qué hago hoy" hero.
 *
 * Renders:
 *   1. <ClosingSoon7dWidget> — Próximos cierres (7 días) at the TOP of the zone
 *   2. <HeroActionList> — a 1-3 item numbered list of concrete actions
 *   3. <details> KPI footer — the 4 legacy stat cards demoted into a collapse
 *   4. <ProfileIncompleteBanner> — if completeness < 80
 *
 * Each zone owns its own useQuery call so a slow endpoint cannot block
 * the others. The page paints incrementally.
 */
"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, Clock, Globe, ListChecks, Sparkles, Target, TrendingUp } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, EmptyState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { TriageOpportunityItem, TriageRead } from "@/lib/types";
import { TriageSkeleton } from "@/components/dashboard/skeletons/TriageSkeleton";

function formatNumber(value: number) {
  return new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 }).format(value);
}

function ClosingSoon7dWidget({ items }: { items: TriageOpportunityItem[] }) {
  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 p-6 text-sm text-slate-500 dark:text-slate-400">
          <CalendarClock className="h-5 w-5" />
          Sin cierres esta semana.
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <CalendarClock className="h-5 w-5 text-cyan-600 dark:text-cyan-400" />
              Próximos cierres
            </CardTitle>
            <CardDescription>Convocatorias que cierran esta semana.</CardDescription>
          </div>
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-cyan-100 text-sm font-bold text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200">
            {items.length}
          </span>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => {
          const urgency = item.days_to_close !== null && item.days_to_close <= 3 ? "urgent" : item.days_to_close !== null && item.days_to_close <= 7 ? "soon" : "normal";
          const borderColor = urgency === "urgent" ? "border-l-rose-500" : urgency === "soon" ? "border-l-amber-500" : "border-l-sky-500";
          const daysText = item.days_to_close === 0 ? "Hoy" : item.days_to_close === 1 ? "1 día" : `${item.days_to_close} días`;
          const progress = item.days_to_close !== null ? Math.max(0, Math.min(100, ((7 - item.days_to_close) / 7) * 100)) : 0;

          return (
            <Link key={item.id} href={`/opportunities/${item.id}`} className="group block">
              <div className={`rounded-lg border border-slate-200 bg-white p-4 transition-all hover:shadow-md hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-600 border-l-4 ${borderColor}`}>
                <p className="line-clamp-2 text-sm font-medium text-slate-950 group-hover:text-cyan-700 dark:text-white dark:group-hover:text-cyan-300">
                  {item.title}
                </p>
                <div className="mt-3 flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
                  <span className="flex items-center gap-1">
                    <Globe className="h-3 w-3" />
                    {item.country || "—"}
                  </span>
                  {item.score !== null && (
                    <span className="flex items-center gap-1">
                      <TrendingUp className="h-3 w-3" />
                      {item.score}
                    </span>
                  )}
                </div>
                <div className="mt-3 flex items-center justify-between">
                  <Badge tone={urgency === "urgent" ? "destructive" : urgency === "soon" ? "medium" : "muted"}>
                    <Clock className="mr-1 h-3 w-3" />
                    {daysText}
                  </Badge>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {item.funding_amount !== null
                      ? `${formatNumber(item.funding_amount)}${item.currency ? ` ${item.currency}` : ""}`
                      : "—"}
                  </span>
                </div>
                {item.days_to_close !== null && (
                  <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div
                      className={`h-full rounded-full transition-all ${
                        urgency === "urgent" ? "bg-rose-500" : urgency === "soon" ? "bg-amber-500" : "bg-sky-500"
                      }`}
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                )}
              </div>
            </Link>
          );
        })}
      </CardContent>
    </Card>
  );
}

function HeroActionList({ count, hasClosingSoon7d, hasReviewQueue }: {
  count: { review_queue: number; closing_soon_7d: number };
  hasClosingSoon7d: boolean;
  hasReviewQueue: boolean;
}) {
  const items: { kind: string; label: string; cta_href: string; cta_label: string; icon: typeof Target; severity: "urgent" | "info" }[] = [];

  if (hasClosingSoon7d) {
    items.push({
      kind: "deadline",
      label: `${count.closing_soon_7d} convocatoria${count.closing_soon_7d === 1 ? "" : "s"} cierra${count.closing_soon_7d === 1 ? "" : "n"} esta semana`,
      cta_href: "#closing-soon-7d",
      cta_label: "Ver",
      icon: Target,
      severity: "urgent",
    });
  }
  if (hasReviewQueue) {
    items.push({
      kind: "review",
      label: `${count.review_queue} item${count.review_queue === 1 ? "" : "s"} en tu cola de revisión`,
      cta_href: "#review-queue",
      cta_label: "Revisar",
      icon: ListChecks,
      severity: "info",
    });
  }
  items.push({
    kind: "profile",
    label: "Refuerza tu perfil institucional para mejorar la compatibilidad",
    cta_href: "/onboarding",
    cta_label: "Completar",
    icon: Sparkles,
    severity: "info",
  });

  return (
    <Card>
      <div className="border-b border-slate-200 p-4 dark:border-slate-700">
        <h2 className="text-sm font-semibold text-slate-950 dark:text-white">
          Qué hago hoy
        </h2>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Acciones prioritarias basadas en tu radar.
        </p>
      </div>
      <CardContent className="space-y-3 pt-4">
        {items.map((item, index) => {
          const Icon = item.icon;
          return (
            <div
              key={item.kind}
              className="flex items-center gap-3 rounded-md border border-slate-200 p-3 dark:border-slate-700"
            >
              <span
                className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                  item.severity === "urgent"
                    ? "bg-rose-500/10 text-rose-700 dark:text-rose-200"
                    : "bg-slate-500/10 text-slate-700 dark:text-slate-200"
                }`}
              >
                {index + 1}
              </span>
              <Icon className="h-4 w-4 shrink-0 text-slate-500" />
              <p className="flex-1 text-sm text-slate-700 dark:text-slate-200">
                {item.label}
              </p>
              <Link
                href={item.cta_href}
                className="inline-flex h-8 items-center gap-1 rounded-md border border-slate-300 px-3 text-xs font-medium text-slate-900 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-100 dark:hover:bg-slate-800"
              >
                {item.cta_label}
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

const KPI_ACCENTS = [
  { border: "border-t-cyan-500" },
  { border: "border-t-emerald-500" },
  { border: "border-t-amber-500" },
  { border: "border-t-violet-500" },
];

function KpiFooter({ kpis }: { kpis: { total_opportunities: number; open_opportunities: number; closing_soon_opportunities: number; high_match_opportunities: number } }) {
  const items = [
    { label: "Total convocatorias", value: kpis.total_opportunities, accent: KPI_ACCENTS[0] },
    { label: "Con apertura próxima", value: kpis.open_opportunities, accent: KPI_ACCENTS[1] },
    { label: "Cierran pronto", value: kpis.closing_soon_opportunities, accent: KPI_ACCENTS[2] },
    { label: "En revisión", value: kpis.high_match_opportunities, accent: KPI_ACCENTS[3] },
  ];
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className={`rounded-lg border border-slate-200 bg-white p-4 transition-all hover:shadow-md dark:border-slate-800 dark:bg-slate-900 border-t-4 ${item.accent.border}`}>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{item.label}</p>
          <p className="mt-1 text-2xl font-bold text-slate-950 dark:text-white">{formatNumber(item.value)}</p>
        </div>
      ))}
    </div>
  );
}

export function TriageZone() {
  const query = useQuery<TriageRead>({
    queryKey: ["dashboard-triage"],
    queryFn: api.dashboardTriage,
    placeholderData: keepPreviousData,
  });

  if (query.isLoading) return <TriageSkeleton />;
  if (query.error) return <ErrorState message={query.error.message} />;
  if (!query.data) return <EmptyState title="Sin datos de triage" detail="No se recibió información del servidor." />;

  const data = query.data;
  const closingSoonCount = data.closing_soon_7d?.length ?? 0;
  const reviewCount = data.review_queue?.length ?? 0;

  return (
    <div className="space-y-4" data-zone="triage">
      <KpiFooter
        kpis={{
          total_opportunities: closingSoonCount + reviewCount,
          open_opportunities: closingSoonCount,
          closing_soon_opportunities: closingSoonCount,
          high_match_opportunities: reviewCount,
        }}
      />
      <div id="closing-soon-7d">
        <ClosingSoon7dWidget items={data.closing_soon_7d ?? []} />
      </div>
      <div id="review-queue">
        <HeroActionList
          count={{ review_queue: reviewCount, closing_soon_7d: closingSoonCount }}
          hasClosingSoon7d={closingSoonCount > 0}
          hasReviewQueue={reviewCount > 0}
        />
      </div>
    </div>
  );
}
