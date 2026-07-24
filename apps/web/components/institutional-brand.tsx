import Image from "next/image";
import Link from "next/link";

import { cn } from "@/lib/utils";

const SHIELD_URL = "https://www.colmayor.edu.co/wp-content/uploads/2018/11/colmayor-mobile.svg";

export function InstitutionalBrand({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <Link href="/dashboard" className={cn("flex min-w-0 items-center gap-3", className)} aria-label="Ir al panel principal">
      <span className="brand-shield">
        <Image
          src={SHIELD_URL}
          alt="Escudo de la Institución Universitaria Colegio Mayor de Antioquia"
          width={48}
          height={48}
          priority={!compact}
        />
      </span>
      <span className="min-w-0">
        <span className="block text-[10px] font-bold uppercase tracking-[0.16em] text-[#00807d] dark:text-[#61d5d1]">Colmayor</span>
        <span className={cn("block font-semibold leading-tight text-slate-950 dark:text-white", compact ? "text-sm" : "text-[15px]")}>
          Observatorio de Convocatorias
        </span>
        {!compact ? <span className="mt-0.5 block text-[10px] text-slate-500 dark:text-slate-400">Institucional</span> : null}
      </span>
    </Link>
  );
}
