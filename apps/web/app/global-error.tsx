"use client";

/**
 * Global error boundary (Next.js convention). Must render its own
 * <html>/<body> shell because it activates when the root layout itself fails.
 */

import { RouteErrorBoundary, type RouteErrorBoundaryProps } from "@/components/route-error-boundary";

export default function GlobalErrorPage(props: RouteErrorBoundaryProps) {
  return (
    <html lang="es">
      <body data-testid="global-error-body" className="bg-[#f3f6fb] font-sans text-slate-950 antialiased dark:bg-[#07111c] dark:text-slate-100">
        <div className="flex min-h-screen items-center justify-center px-4">
          <RouteErrorBoundary {...props} />
        </div>
      </body>
    </html>
  );
}
