"use client";

import { Bell, Database, Gauge, LogOut, Menu, Radar, Search, Settings, Shield, Target, UserRound, FileText } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ComponentType } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingState } from "@/components/ui/state";
import { ThemeToggle } from "@/components/theme-toggle";
import { api, clearToken, getToken } from "@/lib/api";
import { cn } from "@/lib/utils";

const mainNav = [
  { href: "/dashboard", label: "Panel", icon: Gauge },
  { href: "/opportunities", label: "Convocatorias", icon: Target },
  { href: "/sources", label: "Fuentes", icon: Database },
  { href: "/reports", label: "Reportes", icon: FileText },
  { href: "/alerts", label: "Alertas", icon: Bell },
];

const supportNav = [
  { href: "/onboarding", label: "Perfil", icon: UserRound },
  { href: "/admin", label: "Administración", icon: Shield },
  { href: "/settings", label: "Configuración", icon: Settings },
];

function NavLink({
  href,
  label,
  icon: Icon,
  active,
  onClick,
}: {
  href: string;
  label: string;
  icon: ComponentType<{ className: string }>;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        "flex h-11 items-center gap-3 rounded-lg px-3 text-sm text-slate-700 transition-colors hover:bg-slate-100 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-white/5 dark:hover:text-white",
        active && "bg-cyan-50 text-cyan-800 ring-1 ring-cyan-200 dark:bg-cyan-400/10 dark:text-cyan-200 dark:ring-cyan-400/20",
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span>{label}</span>
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [hasToken, setHasToken] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);

  const me = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    enabled: hasToken,
    retry: false,
  });

  useEffect(() => {
    const token = getToken();
    setHasToken(Boolean(token));
    setAuthChecked(true);
    if (!token) router.replace("/login");
  }, [router]);

  useEffect(() => {
    if (me.isError) {
      clearToken();
      setHasToken(false);
      router.replace("/login");
    }
  }, [me.isError, router]);

  function logout() {
    clearToken();
    setHasToken(false);
    router.push("/login");
  }

  const userInitials = useMemo(() => {
    const name = me.data?.name ?? "U";
    return (
      name
        .split(" ")
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase() ?? "")
        .join("") || "U"
    );
  }, [me.data?.name]);

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="mb-8 flex items-center gap-3 px-2">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-cyan-200 bg-cyan-50 text-cyan-700 shadow-[0_0_24px_rgba(13,78,94,0.08)] dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-200">
          <Radar className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-base font-semibold text-slate-900 dark:text-white">ConvocaRadar IA</p>
          <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">Inteligencia empresarial</p>
        </div>
      </div>

      <div className="space-y-1">
        {mainNav.map((item) => {
          const Icon = item.icon;
          return <NavLink key={item.href} href={item.href} label={item.label} icon={Icon} active={pathname === item.href} onClick={() => setOpen(false)} />;
        })}
      </div>

      <div className="mt-8 border-t border-slate-200 pt-4 dark:border-slate-800">
        <div className="space-y-1">
          {supportNav.map((item) => {
            const Icon = item.icon;
            return <NavLink key={item.href} href={item.href} label={item.label} icon={Icon} active={pathname === item.href} onClick={() => setOpen(false)} />;
          })}
        </div>
      </div>

      <div className="mt-auto rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900/70">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">Sesión activa</p>
        <p className="mt-1 truncate text-sm font-medium text-slate-900 dark:text-white">{me.data?.name ?? "Validando sesión..."}</p>
        <p className="truncate text-xs text-slate-500 dark:text-slate-400">{me.data?.role ?? "Cargando rol..."}</p>
        <Button className="mt-3 w-full justify-start" variant="outline" onClick={logout}>
          <LogOut className="h-4 w-4" />
          Salir
        </Button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950 dark:bg-slate-950 dark:text-slate-100">
      <aside className="fixed left-0 top-0 hidden h-screen w-72 border-r border-slate-200 bg-white px-4 py-5 lg:block dark:border-slate-800 dark:bg-slate-950">
        {sidebar}
      </aside>

      {open ? (
        <div className="fixed inset-0 z-40 bg-slate-950/55 lg:hidden" onClick={() => setOpen(false)}>
          <aside className="h-full w-80 border-r border-slate-200 bg-white px-4 py-5 dark:border-slate-800 dark:bg-slate-950" onClick={(event) => event.stopPropagation()}>
            {sidebar}
          </aside>
        </div>
      ) : null}

      <main className="lg:pl-72">
        <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/90">
          <div className="flex h-16 items-center gap-3 px-4 lg:px-6">
            <Button variant="outline" size="icon" className="lg:hidden" onClick={() => setOpen(true)}>
              <Menu className="h-5 w-5" />
            </Button>

            <div className="relative hidden flex-1 items-center lg:flex">
              <Search className="pointer-events-none absolute left-3 h-4 w-4 text-slate-500" />
              <Input className="h-10 rounded-lg border-slate-200 bg-white pl-9 text-sm placeholder:text-slate-500 dark:border-slate-800 dark:bg-slate-900/70" placeholder="Buscar en ConvocaRadar IA..." />
            </div>

            <div className="ml-auto flex items-center gap-2">
              <ThemeToggle />
              <div className="flex h-10 w-10 items-center justify-center rounded-full border border-cyan-200 bg-cyan-50 text-xs font-semibold text-cyan-700 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-200">
                {userInitials}
              </div>
            </div>
          </div>
        </header>

        <div className="mx-auto max-w-7xl px-4 py-6 lg:px-6">{!authChecked || !hasToken || me.isLoading ? <LoadingState label="Validando sesión" /> : children}</div>
      </main>
    </div>
  );
}
