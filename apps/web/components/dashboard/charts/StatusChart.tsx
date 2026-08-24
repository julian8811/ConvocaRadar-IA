"use client";

/**
 * Code-split wrapper (REQ-FE-CHARTS-1): Recharts lives behind a
 * next/dynamic ssr:false boundary so it stays out of the initial bundle
 * and never renders on the server.
 */

import dynamic from "next/dynamic";

import type { DashboardBreakdownItem } from "@/lib/types";

const ChartClient = dynamic(() => import("./StatusChartClient"), { ssr: false });

export function StatusChart({ data }: { data: DashboardBreakdownItem[] }) {
  return <ChartClient data={data} />;
}

export default StatusChart;
