"use client";

import { AlertTriangle, Bell, Database, FileText, Gauge, LogOut, Menu, Radar, RefreshCw, Search, Settings, Shield, Target, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type ComponentType, type FormEvent, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
  icon: ComponentType<{ className?: string }>;
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

/**
 * SEC-1.5: is a thrown error a fetch AbortError (network timeout from
 * AbortController inside request())?
 *
 * Browsers use DOMException with name "AbortError" for AbortController-driven
 * cancellations, but our request() may also surface a plain Error with the
 * name "AbortError" if the underlying fetch failed that way.
 */
function isAbortError(error: unknown): boolean {
  if (!error) return false;
  if (typeof error === "object" && "name" in error) {
    return (error as { name: string }).name === "AbortError";
  }
  return false;
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [headerSearch, setHeaderSearch] = useState("");
  const [hasToken] = useState(() => Boolean(getToken()));

  // SEC-1.5: retry: 1 with retryDelay: 1000 so transient network blips are
  // absorbed by react-query. We must still distinguish AbortError from real
  // auth failures in the useEffect below.
  const me = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    enabled: hasToken,
    retry: 1,
    retryDelay: 1000,
  });

  // SEC-1.5: track whether the user has manually clicked the "Reintentar"
  // button after the automatic retry also failed. Two consecutive AbortErrors
  // (initial + retry, or retry + manual) → redirect to /login with reason.
  const [manualRetryDone, setManualRetryDone] = useState(false);
  // Reset the manual-retry flag only when the query has SUCCEEDED (has data).
  // Resetting on isError=false would clobber the flag during a new fetch and
  // let the user retry forever after one transient blip.
  //
  // eslint-disable-next-line react-hooks/set-state-in-effect -- the
  // "reset only on success" semantics require a side effect because the
  // trigger (me.isSuccess flipping true) is not a user action; deriving
  // the flag from the query would conflate "user clicked retry" with
  // "query had an error" in transient cases.
  useEffect(() => {
    if (me.isSuccess) {
      setManualRetryDone(false);
    }
  }, [me.isSuccess]);

  // SEC-1.5 error routing:
  //   - No token at all      → /login (immediate)
  //   - Non-AbortError       → /login (real auth failure, no retry UI)
  //   - AbortError w/ manual retry done → /login?reason=session_expired
  //   - AbortError first time → show the error UI with "Reintentar" button
  useEffect(() => {
    if (!hasToken) {
      router.replace("/login");
      return;
    }
    if (!me.isError) return;
    if (!isAbortError(me.error)) {
      clearToken();
      router.replace("/login");
      return;
    }
    if (manualRetryDone) {
      // Two consecutive AbortErrors — give up and ask the user to log in
      // again. The cookie will be replaced if they authenticate again.
      router.replace("/login?reason=session_expired");
    }
  }, [hasToken, me.isError, me.error, manualRetryDone, router]);

  const handleRetry = useCallback(() => {
    setManualRetryDone(true);
    void me.refetch();
  }, [me]);

  async function logout() {
    try {
      // Best-effort: clear the cookie on the server. We still redirect even
      // if the call fails (offline, 5xx, etc.) — the local state is the
      // source of truth for the user-visible redirect.
      await api.logout();
    } catch {
      // Ignore — the localStorage mirror (dev only) is cleared below and
      // the user is sent to /login regardless.
    }
    clearToken();
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

  const isAdmin = me.data?.role === "admin";
  const visibleSupportNav = supportNav.filter((item) => item.href !== "/admin" || isAdmin);

  function submitHeaderSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = headerSearch.trim();
    if (!query) {
      router.push("/opportunities");
      return;
    }
    router.push(`/opportunities?semantic=${encodeURIComponent(query)}`);
  }

  // SEC-1.5: render the AbortError UI in place of children. Keeps the
  // sidebar/header visible so the user can still navigate.
  const showAbortErrorUI = Boolean(
    hasToken && me.isError && isAbortError(me.error) && !manualRetryDone,
  );

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
          {visibleSupportNav.map((item) => {
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

            <form className="relative hidden flex-1 items-center lg:flex" onSubmit={submitHeaderSearch}>
              <Search className="pointer-events-none absolute left-3 h-4 w-4 text-slate-500" />
              <Input
                className="h-10 rounded-lg border-slate-200 bg-white pl-9 text-sm placeholder:text-slate-500 dark:border-slate-800 dark:bg-slate-900/70"
                placeholder="Búsqueda semántica de convocatorias..."
                value={headerSearch}
                onChange={(event) => setHeaderSearch(event.target.value)}
              />
            </form>

            <div className="ml-auto flex items-center gap-2">
              <ThemeToggle />
              <div className="flex h-10 w-10 items-center justify-center rounded-full border border-cyan-200 bg-cyan-50 text-xs font-semibold text-cyan-700 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-200">
                {userInitials}
              </div>
            </div>
          </div>
        </header>

        <div className="mx-auto max-w-7xl px-4 py-6 lg:px-6">
          {!hasToken || me.isLoading ? (
            <LoadingState label="Validando sesión" />
          ) : showAbortErrorUI ? (
            <Card className="border-amber-200 bg-amber-50 dark:border-amber-400/30 dark:bg-amber-400/10" role="alert">
              <CardContent className="flex flex-col gap-3 py-6 text-sm text-amber-900 dark:text-amber-100 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-700 dark:text-amber-300" />
                  <div>
                    <p className="font-semibold">No se pudo contactar al servidor</p>
                    <p className="text-amber-800 dark:text-amber-200/80">
                      Revisá tu conexión a internet y volvé a intentarlo.
                    </p>
                  </div>
                </div>
                <Button
                  variant="outline"
                  onClick={handleRetry}
                  disabled={me.isFetching}
                  className="shrink-0 border-amber-300 bg-white text-amber-900 hover:bg-amber-100 dark:border-amber-400/30 dark:bg-slate-950/40 dark:text-amber-100 dark:hover:bg-amber-400/20"
                >
                  <RefreshCw className={`h-4 w-4 ${me.isFetching ? "animate-spin" : ""}`} />
                  Reintentar
                </Button>
              </CardContent>
            </Card>
          ) : (
            children
          )}
        </div>
      </main>
    </div>
  );
}
