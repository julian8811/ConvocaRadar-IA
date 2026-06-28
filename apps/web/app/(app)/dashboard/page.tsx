/**
 * PR B-2 (dashboard-redesign): the new 3-zone dashboard page.
 *
 * Each zone (Triage / Pipeline / Health) is a self-contained component
 * that owns its own useQuery call. The page just composes them
 * top-to-bottom. A slow endpoint cannot block the others, and each
 * zone paints incrementally with its own skeleton.
 *
 * The page is intentionally thin: the design lives in the zone files.
 */
"use client";

import { HealthZone } from "@/components/dashboard/HealthZone";
import { PipelineZone } from "@/components/dashboard/PipelineZone";
import { TriageZone } from "@/components/dashboard/TriageZone";

export default function DashboardPage() {
  return (
    <section className="space-y-6">
      <TriageZone />
      <PipelineZone />
      <HealthZone />
    </section>
  );
}
