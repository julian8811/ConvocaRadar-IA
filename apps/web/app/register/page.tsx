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
import { api, setToken } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setLoading(true);
    setError(null);
    try {
      const response = await api.register({
        name: String(form.get("name") ?? "").trim(),
        email: String(form.get("email") ?? "").trim(),
        password: String(form.get("password") ?? ""),
        organization_name: String(form.get("organization_name") ?? "").trim(),
        organization_type: String(form.get("organization_type") ?? "university").trim(),
        country: String(form.get("country") ?? "Colombia").trim(),
      });
      setToken(response.access_token);
      toast.success("Organización creada");
      router.push("/onboarding");
      router.refresh();
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "No se pudo registrar la organización";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center px-4 py-10">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-lg border-slate-200 bg-white/95 shadow-2xl shadow-slate-900/10 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <CardHeader className="space-y-4 border-b border-slate-200 pb-6 dark:border-slate-800">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-200">
            <Radar className="h-6 w-6" />
          </div>
          <div>
            <CardTitle className="text-2xl text-slate-900 dark:text-white">Crear cuenta</CardTitle>
            <CardDescription>Registra tu organización y activa el monitoreo de convocatorias.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="pt-6">
          <form className="grid gap-4 md:grid-cols-2" onSubmit={onSubmit}>
            <Input className="md:col-span-2" name="organization_name" placeholder="Nombre de la organización" required />
            <Input name="name" placeholder="Tu nombre" required />
            <Input name="email" type="email" placeholder="Correo electrónico" required autoComplete="email" />
            <Input
              className="md:col-span-2"
              name="password"
              type="password"
              placeholder="Contraseña (mínimo 10 caracteres)"
              required
              minLength={10}
              autoComplete="new-password"
            />
            <Input name="organization_type" placeholder="Tipo: university, startup, ngo..." defaultValue="university" />
            <Input name="country" placeholder="País" defaultValue="Colombia" />
            {error ? (
              <div className="md:col-span-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            ) : null}
            <Button className="md:col-span-2" disabled={loading} type="submit">
              {loading ? "Creando cuenta..." : "Registrar organización"}
            </Button>
          </form>
          <p className="mt-4 text-sm text-slate-600 dark:text-slate-400">
            ¿Ya tienes cuenta?{" "}
            <Link href="/login" className="font-medium text-cyan-700 hover:underline dark:text-cyan-300">
              Inicia sesión
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
