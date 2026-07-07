"use client";

import Link from "next/link";
import { Radar } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/theme-toggle";
import { API_URL, api, setToken } from "@/lib/api";

export default function LoginPage() {
  // Env vars are read at render-time so tests can stub them via vi.stubEnv
  const localEmail = process.env.NEXT_PUBLIC_LOCAL_EMAIL || "";
  const localPassword = process.env.NEXT_PUBLIC_LOCAL_PASSWORD || "";
  const isDev = process.env.NEXT_PUBLIC_ENV === "development";

  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState(isDev ? localEmail : "");
  const [password, setPassword] = useState(isDev ? localPassword : "");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await signIn(email, password);
  }

  async function signIn(nextEmail: string, nextPassword: string) {
    setLoading(true);
    setError(null);
    try {
      const response = await api.login(nextEmail.trim(), nextPassword);
      setToken(response.access_token);
      toast.success("Sesión iniciada");
      router.push("/dashboard");
      router.refresh();
    } catch (error) {
      let message = "No se pudo iniciar sesión";
      if (error instanceof TypeError && (error.message === "Failed to fetch" || error.message.includes("NetworkError"))) {
        message = "El servidor no está disponible. Esperá unos segundos y volvé a intentar.";
      } else if (error instanceof Error) {
        message = error.message;
      }
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center px-4">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-md border-slate-200 bg-white/95 shadow-2xl shadow-slate-900/10 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <CardHeader className="space-y-4 border-b border-slate-200 pb-6 dark:border-slate-800">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-200">
            <Radar className="h-6 w-6" />
          </div>
          <div>
            <CardTitle className="text-2xl text-slate-900 dark:text-white">ConvocaRadar IA</CardTitle>
            <CardDescription>Ingresa al tablero de vigilancia de convocatorias.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="pt-6">
          <form className="space-y-4" onSubmit={onSubmit}>
            <Input
              name="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              aria-label="Correo electrónico"
              data-testid="login-email"
              autoComplete="email"
            />
            <Input
              name="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-label="Contraseña"
              data-testid="login-password"
              autoComplete="current-password"
            />
            {error ? (
              <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            ) : null}
              <Button className="w-full" disabled={loading} type="button" onClick={() => signIn(email, password)}>
                {loading ? "Ingresando..." : "Ingresar"}
              </Button>
              {isDev && (
                <Button className="w-full" disabled={loading} type="button" variant="outline" onClick={() => signIn(localEmail, localPassword)}>
                  Entrar con cuenta local
                </Button>
              )}
              {API_URL?.includes("onrender") && (
                <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
                  El servidor puede tardar hasta 30s en responder si estaba en pausa.
                </p>
              )}
          </form>
          <p className="mt-4 text-xs text-slate-500">
            API configurada: <span className="font-mono">{API_URL}</span>
          </p>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            ¿Primera vez aquí?{" "}
            <Link href="/register" className="font-medium text-cyan-700 hover:underline dark:text-cyan-300">
              Crear cuenta
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
