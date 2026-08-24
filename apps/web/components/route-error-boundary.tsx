"use client";

/**
 * Shared recovery UI for Next.js route-segment error boundaries
 * (app/error.tsx, app/(app)/error.tsx, app/global-error.tsx).
 *
 * REQ-FE-BOUNDARY-1: a render-time error (e.g. a dashboard chart throwing)
 * must surface recovery UI with a retry affordance instead of a blank page.
 * `reset()` re-renders the segment client-side without a full reload.
 */

import { Button } from "@/components/ui/button";

export interface RouteErrorBoundaryProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export function RouteErrorBoundary({ error, reset }: RouteErrorBoundaryProps) {
  return (
    <div
      role="alert"
      className="flex min-h-[60vh] w-full max-w-md flex-col items-center justify-center gap-4 rounded-xl border border-slate-200 bg-white/95 p-8 text-center shadow-lg dark:border-slate-800 dark:bg-slate-950/90"
    >
      <h2 className="text-xl font-semibold text-slate-900 dark:text-white">Algo salió mal</h2>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Ocurrió un error al mostrar esta sección. Podés reintentar sin perder el resto de la página.
      </p>
      <p data-testid="route-error-message" className="break-all font-mono text-xs text-slate-500 dark:text-slate-500">
        {error.message}
      </p>
      {error.digest ? (
        <p className="font-mono text-[10px] uppercase tracking-wide text-slate-400 dark:text-slate-600">
          Digest: {error.digest}
        </p>
      ) : null}
      <Button type="button" onClick={reset}>
        Reintentar
      </Button>
    </div>
  );
}
