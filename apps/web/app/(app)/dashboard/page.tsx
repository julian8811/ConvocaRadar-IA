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

import { ArrowRight, CalendarClock, Radar } from "lucide-react";
import Link from "next/link";

import { HealthZone } from "@/components/dashboard/HealthZone";
import { PipelineZone } from "@/components/dashboard/PipelineZone";
import { TriageZone } from "@/components/dashboard/TriageZone";

export default function DashboardPage() {
  return (
    <section className="space-y-6">
      <div className="institutional-hero relative overflow-hidden rounded-[28px] bg-[#005652] px-6 py-7 text-white shadow-[0_24px_60px_-30px_rgba(0,86,82,.75)] lg:px-9 lg:py-9">
        <div className="absolute -right-16 -top-24 h-72 w-72 rounded-full border-[42px] border-white/5" />
        <div className="absolute bottom-0 right-16 h-28 w-28 translate-y-1/2 rounded-full bg-[#bed630]/25 blur-2xl" />
        <div className="relative grid gap-8 xl:grid-cols-[1fr_auto] xl:items-end">
          <div>
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-white/90">
              <Radar className="h-3.5 w-3.5" />
              Inteligencia institucional
            </div>
            <h1 className="max-w-3xl text-3xl font-semibold leading-tight tracking-[-0.03em] sm:text-4xl">
              Observatorio de Convocatorias Institucional
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-white/75 sm:text-base">
              Panorama estratégico de oportunidades nacionales e internacionales para investigación, innovación y cooperación.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link href="/opportunities" className="inline-flex h-11 items-center gap-2 rounded-full bg-[#bed630] px-5 text-sm font-semibold text-[#183b36] transition hover:bg-[#d3e75f]">
              Explorar convocatorias <ArrowRight className="h-4 w-4" />
            </Link>
            <Link href="/sources" className="inline-flex h-11 items-center gap-2 rounded-full border border-white/25 bg-white/10 px-5 text-sm font-semibold text-white transition hover:bg-white/20">
              <Radar className="h-4 w-4" /> Ver fuentes
            </Link>
          </div>
        </div>
        <div className="relative mt-7 flex items-center gap-2 border-t border-white/15 pt-4 text-xs text-white/65">
          <CalendarClock className="h-4 w-4 text-[#bed630]" />
          Información consolidada para la toma de decisiones institucionales
        </div>
      </div>
      <TriageZone />
      <PipelineZone />
      <HealthZone />
    </section>
  );
}
