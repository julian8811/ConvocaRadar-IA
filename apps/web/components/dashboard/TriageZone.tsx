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
import { ArrowRight, ListChecks, Sparkles, Target } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorState, EmptyState } from "@/components/ui/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { TriageOpportunityItem, TriageRead } from "@/lib/types";
import { TriageSkeleton } from "@/components/dashboard/skeletons/TriageSkeleton";

function formatNumber(value: number) {
  return new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 }).format(value);
}

function formatPercent(value: number) {
  return `${Math.round(value)}%`;
}

function ClosingSoon7dWidget({ items }: { items: TriageOpportunityItem[] }) {
  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="p-4 text-sm text-slate-500 dark:text-slate-400">
          Sin cierres esta semana.
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <div className="border-b border-slate-200 p-4 dark:border-slate-700">
        <h2 className="text-sm font-semibold text-slate-950 dark:text-white">
          Próximos cierres (7 días)
        </h2>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Convocatorias que cierran esta semana.
        </p>
      </div>
      <div className="overflow-x-auto p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Convocatoria</TableHead>
              <TableHead>País</TableHead>
              <TableHead>Cierra en</TableHead>
              <TableHead>Monto</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.id}>
                <TableCell>
                  <Link
                    href={`/opportunities/${item.id}`}
                    className="font-medium text-slate-950 hover:text-cyan-700 dark:text-white dark:hover:text-cyan-200"
                  >
                    {item.title}
                  </Link>
                </TableCell>
                <TableCell>{item.country || "Sin dato"}</TableCell>
                <TableCell>
                  {item.days_to_close !== null ? (
                    <Badge
                      tone={
                        item.days_to_close <= 3
                          ? "destructive"
                          : item.days_to_close <= 7
                            ? "medium"
                            : "muted"
                      }
                    >
                      {item.days_to_close === 0
                        ? "Hoy"
                        : item.days_to_close === 1
                          ? "1 día"
                          : `${item.days_to_close} días`}
                    </Badge>
                  ) : (
                    <span className="text-xs text-slate-500 dark:text-slate-400">—</span>
                  )}
                </TableCell>
                <TableCell className="text-xs text-slate-500 dark:text-slate-400">
                  {item.funding_amount !== null
                    ? `${formatNumber(item.funding_amount)}${item.currency ? ` ${item.currency}` : ""}`
                    : "Por validar"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
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

function ProfileIncompleteBanner({ completeness, missingFields }: {
  completeness: number;
  missingFields: string[];
}) {
  if (completeness >= 80) return null;
  return (
    <Card className="border-cyan-500/30 bg-cyan-500/5">
      <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium text-slate-950 dark:text-white">
            Perfil al {formatPercent(completeness)} — mejora la compatibilidad de tus scores
          </p>
          {missingFields.length > 0 ? (
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
              Falta completar: {missingFields.join(", ")}.
            </p>
          ) : null}
        </div>
        <Link
          href="/onboarding"
          className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-4 text-sm font-medium text-slate-900 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800"
        >
          Completar perfil
          <ArrowRight className="h-4 w-4" />
        </Link>
      </CardContent>
    </Card>
  );
}

function KpiFooter({ kpis }: { kpis: { total_opportunities: number; open_opportunities: number; closing_soon_opportunities: number; high_match_opportunities: number } }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <div className="rounded-md border border-slate-200 bg-white p-3 text-xs dark:border-slate-800 dark:bg-slate-900">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">Total convocatorias</p>
        <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">{formatNumber(kpis.total_opportunities)}</p>
      </div>
      <div className="rounded-md border border-slate-200 bg-white p-3 text-xs dark:border-slate-800 dark:bg-slate-900">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">Convocatorias abiertas</p>
        <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">{formatNumber(kpis.open_opportunities)}</p>
      </div>
      <div className="rounded-md border border-slate-200 bg-white p-3 text-xs dark:border-slate-800 dark:bg-slate-900">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">Cierran pronto</p>
        <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">{formatNumber(kpis.closing_soon_opportunities)}</p>
      </div>
      <div className="rounded-md border border-slate-200 bg-white p-3 text-xs dark:border-slate-800 dark:bg-slate-900">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">Alta compatibilidad</p>
        <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">{formatNumber(kpis.high_match_opportunities)}</p>
      </div>
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
  const profile = data.profile ?? { completeness: 0, missing_fields: [] };

  // kpis: pull from the review queue + closing-soon 7d slice (slim, no entity/status).
  const kpis = {
    total_opportunities: closingSoonCount + reviewCount,
    open_opportunities: 0,
    closing_soon_opportunities: closingSoonCount,
    high_match_opportunities: 0,
  };

  return (
    <div className="space-y-4" data-zone="triage">
      <ProfileIncompleteBanner completeness={profile.completeness} missingFields={profile.missing_fields} />
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
      <details className="rounded-md border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <summary className="cursor-pointer text-sm font-medium text-slate-700 dark:text-slate-200">
          Ver resumen numérico
        </summary>
        <div className="mt-3">
          <KpiFooter kpis={kpis} />
        </div>
      </details>
    </div>
  );
}
