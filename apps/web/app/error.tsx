"use client";

/**
 * Root route-segment error boundary (Next.js convention).
 * Catches uncaught render errors for segments outside the (app) group.
 */

import { RouteErrorBoundary, type RouteErrorBoundaryProps } from "@/components/route-error-boundary";

export default function ErrorPage(props: RouteErrorBoundaryProps) {
  return <RouteErrorBoundary {...props} />;
}
