"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useState, Suspense } from "react";
import { toast } from "sonner";
import { ArrowLeft, CheckCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/theme-toggle";
import { InstitutionalBrand } from "@/components/institutional-brand";
import { API_URL } from "@/lib/api";

function ResetForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password !== confirm) {
      setError("Las contraseñas no coinciden");
      return;
    }
    if (password.length < 10) {
      setError("La contraseña debe tener al menos 10 caracteres");
      return;
    }
    if (!token) {
      setError("Token de recuperación inválido");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_URL}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Error al restablecer la contraseña");
      }
      setDone(true);
      toast.success("Contraseña actualizada");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Error al restablecer la contraseña";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  if (done) {
    return (
      <div className="flex flex-col items-center gap-4 py-4 text-center">
        <CheckCircle className="h-12 w-12 text-[#00b3af]" />
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Tu contraseña fue actualizada correctamente.
        </p>
        <Link href="/login" className="mt-2 text-sm font-semibold text-[#006b66] hover:text-[#004945] dark:text-[#74ddd8]">
          <ArrowLeft className="mr-1 inline h-4 w-4" />
          Iniciar sesión
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div>
        <label htmlFor="password" className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
          Nueva contraseña
        </label>
        <Input
          id="password"
          type="password"
          placeholder="Mínimo 10 caracteres"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={10}
          autoFocus
        />
      </div>
      <div>
        <label htmlFor="confirm" className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
          Confirmar contraseña
        </label>
        <Input
          id="confirm"
          type="password"
          placeholder="Repetí la contraseña"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
          minLength={10}
        />
      </div>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      <Button type="submit" className="w-full" disabled={loading || !token}>
        {loading ? "Actualizando..." : "Restablecer contraseña"}
      </Button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <main className="auth-surface relative flex min-h-screen items-center justify-center px-4 py-12">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-md overflow-hidden border-slate-200 bg-white/95 shadow-2xl shadow-[#005652]/10 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <CardHeader className="border-b border-slate-200 pb-6 dark:border-slate-800">
          <InstitutionalBrand />
          <CardTitle className="mt-4 text-slate-950 dark:text-white">
            Restablecer contraseña
          </CardTitle>
          <CardDescription>
            Ingresá tu nueva contraseña.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-6">
          <Suspense fallback={<div className="py-8 text-center text-sm text-slate-500">Cargando...</div>}>
            <ResetForm />
          </Suspense>
        </CardContent>
      </Card>
    </main>
  );
}
