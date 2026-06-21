import * as React from "react";

import { cn } from "@/lib/utils";

const styles: Record<string, string> = {
  open: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200",
  closing_soon: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200",
  closed: "border-slate-500/30 bg-slate-500/10 text-slate-700 dark:text-slate-300",
  healthy: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200",
  degraded: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200",
  failing: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-200",
  idle: "border-slate-500/30 bg-slate-500/10 text-slate-700 dark:text-slate-300",
  high: "border-cyan-500/30 bg-cyan-500/10 text-cyan-700 dark:text-cyan-200",
  medium: "border-indigo-500/30 bg-indigo-500/10 text-indigo-700 dark:text-indigo-200",
  low: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200",
  not_recommended: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-200",
};

export function Badge({ className, tone, ...props }: React.HTMLAttributes<HTMLSpanElement> & { tone: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium tracking-[0.01em]",
        (tone ? styles[tone] : null) ?? "border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200",
        className,
      )}
      {...props}
    />
  );
}
