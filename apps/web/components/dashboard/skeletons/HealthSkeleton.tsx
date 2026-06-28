/**
 * PR B-2 (dashboard-redesign): Per-zone loading skeleton for the Health
 * zone. Card shimmer (KPI strip + data coverage) + 2 chart shimmers
 * (Status, Country).
 */
export function HealthSkeleton() {
  return (
    <div
      data-testid="health-skeleton"
      data-zone-skeleton="health"
      className="space-y-4"
      aria-busy="true"
      aria-label="Cargando salud"
    >
      <div className="rounded-md border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="h-5 w-1/3 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-20 w-full animate-pulse rounded bg-slate-200 dark:bg-slate-700"
            />
          ))}
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {[0, 1].map((i) => (
          <div
            key={i}
            className="h-72 w-full animate-pulse rounded-md border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900"
          />
        ))}
      </div>
    </div>
  );
}
