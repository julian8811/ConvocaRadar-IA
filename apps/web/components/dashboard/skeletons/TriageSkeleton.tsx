/**
 * PR B-2 (dashboard-redesign): Per-zone loading skeleton for the Triage
 * zone. Uses Tailwind's `animate-pulse` directly (no custom Skeleton
 * primitive needed). The shape mirrors the Triage zone layout:
 *  - ClosingSoon7dWidget placeholder
 *  - 1-line hero action placeholder
 *  - KPI <details> footer placeholder
 */
export function TriageSkeleton() {
  return (
    <div
      data-testid="triage-skeleton"
      data-zone-skeleton="triage"
      className="space-y-4"
      aria-busy="true"
      aria-label="Cargando triage"
    >
      <div className="rounded-md border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="h-5 w-1/3 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
        <div className="mt-4 space-y-2">
          <div className="h-4 w-full animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
          <div className="h-4 w-5/6 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
          <div className="h-4 w-2/3 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
        </div>
      </div>
      <div className="rounded-md border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="h-4 w-1/2 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
        <div className="mt-3 h-10 w-full animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      </div>
    </div>
  );
}
