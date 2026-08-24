"use client";

/**
 * Dashboard route-group error boundary. Every page inside (app) — dashboard,
 * admin, opportunities, alerts, reports, settings, sources, onboarding —
 * recovers here instead of blanking out when a chart or panel throws.
 */

import { RouteErrorBoundary, type RouteErrorBoundaryProps } from "@/components/route-error-boundary";

export default function AppGroupErrorPage(props: RouteErrorBoundaryProps) {
  return <RouteErrorBoundary {...props} />;
}
