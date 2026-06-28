/**
 * PR B-2 (dashboard-redesign): Extracted from the old monolithic
 * dashboard page. The legacy row rendered the same columns for both
 * top_scored and closing_soon — both new tables now need different
 * shapes (Razones vs Cierra en countdown). This component accepts
 * feature flags so each table picks the columns it needs.
 *
 * Variant A (default) — legacy 5 columns: Convocatoria, País, Score, Plazo, Monto.
 * Variant B — when showReasons=true, replaces Plazo with Razones (joined, +N más).
 * Variant C — when showCountdown=true, replaces Plazo with Cierra en (red/amber/plain).
 * Variant D — when showStatusBadge=true (review queue), adds an En revisión badge.
 */
"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { TableCell, TableRow } from "@/components/ui/table";
import { decodeVisibleText, isNoiseVisibleText } from "@/lib/text";
import type { PipelineOpportunityItem } from "@/lib/types";

const REASONS_VISIBLE = 2;

function formatNumber(value: number) {
  return new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 }).format(value);
}

function visibleTitle(title: string) {
  const text = decodeVisibleText(title, "");
  return isNoiseVisibleText(text) ? "Convocatoria sin título legible" : text || "Convocatoria sin título legible";
}

function formatAmount(item: PipelineOpportunityItem) {
  if (item.funding_amount === null) return "Por validar";
  const currency = item.currency ? ` ${item.currency}` : "";
  return `${formatNumber(item.funding_amount)}${currency}`;
}

function countdownTone(days: number): "destructive" | "medium" | "muted" {
  if (days <= 3) return "destructive";
  if (days <= 7) return "medium";
  return "muted";
}

function countdownLabel(days: number) {
  if (days === 0) return "Hoy";
  if (days === 1) return "1 día";
  return `${days} días`;
}

export function OpportunityRow({
  item,
  showReasons = false,
  showCountdown = false,
  showStatusBadge = false,
}: {
  item: PipelineOpportunityItem;
  showReasons?: boolean;
  showCountdown?: boolean;
  showStatusBadge?: boolean;
}) {
  return (
    <TableRow>
      <TableCell className="max-w-xs">
        <Link
          href={`/opportunities/${item.id}`}
          className="font-medium text-slate-950 hover:text-cyan-700 dark:text-white dark:hover:text-cyan-200"
        >
          {visibleTitle(item.title)}
        </Link>
        {showStatusBadge ? (
          <p className="mt-1">
            <Badge tone="review">En revisión</Badge>
          </p>
        ) : null}
      </TableCell>
      <TableCell>{item.country || "Sin dato"}</TableCell>
      <TableCell>
        {item.score !== null ? (
          <div className="space-y-1">
            <p className="font-medium text-slate-950 dark:text-white">{Math.round(item.score)}</p>
          </div>
        ) : (
          <span className="text-xs text-slate-500 dark:text-slate-400">Sin calcular</span>
        )}
      </TableCell>
      {showReasons ? (
        <TableCell className="max-w-xs text-xs text-slate-600 dark:text-slate-300">
          {item.reasons.length === 0 ? (
            <span className="text-xs text-slate-500 dark:text-slate-400">Sin razones registradas</span>
          ) : (
            <ul className="space-y-0.5">
              {item.reasons.slice(0, REASONS_VISIBLE).map((reason, index) => (
                <li key={`${item.id}-reason-${index}`}>{reason}</li>
              ))}
              {item.reasons.length > REASONS_VISIBLE ? (
                <li className="text-cyan-700 dark:text-cyan-200">
                  +{item.reasons.length - REASONS_VISIBLE} más
                </li>
              ) : null}
            </ul>
          )}
        </TableCell>
      ) : showCountdown ? (
        <TableCell>
          {item.days_to_close !== null ? (
            <Badge tone={countdownTone(item.days_to_close)}>{countdownLabel(item.days_to_close)}</Badge>
          ) : (
            <span className="text-xs text-slate-500 dark:text-slate-400">Sin fecha</span>
          )}
        </TableCell>
      ) : (
        <TableCell>
          {item.days_to_close !== null ? (
            <span>{item.days_to_close} d</span>
          ) : (
            <span className="text-xs text-slate-500 dark:text-slate-400">—</span>
          )}
        </TableCell>
      )}
      <TableCell className="text-xs text-slate-500 dark:text-slate-400">{formatAmount(item)}</TableCell>
    </TableRow>
  );
}
