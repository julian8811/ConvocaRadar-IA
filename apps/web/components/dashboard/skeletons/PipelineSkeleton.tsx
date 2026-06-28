/**
 * PR B-2 (dashboard-redesign): Per-zone loading skeleton for the Pipeline
 * zone. 3 stacked table shimmers (Top compatibilidad, Cierran pronto,
 * Mi cola de revisión).
 */
export function PipelineSkeleton() {
  return (
    <div
      data-testid="pipeline-skeleton"
      data-zone-skeleton="pipeline"
      className="space-y-4"
      aria-busy="true"
      aria-label="Cargando pipeline"
    >
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="rounded-md border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
        >
          <div className="h-5 w-1/4 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
          <div className="mt-4 space-y-2">
            <div className="h-4 w-full animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
            <div className="h-4 w-3/4 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
            <div className="h-4 w-2/3 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
          </div>
        </div>
      ))}
    </div>
  );
}
