"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { toast } from "sonner";
import { ArrowLeft, CheckCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/theme-toggle";
import { InstitutionalBrand } from "@/components/institutional-brand";
import { API_URL } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_URL}/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Error al enviar el correo");
      }
      setSent(true);
      toast.success("Correo enviado");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Error al enviar el correo";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-surface relative flex min-h-screen items-center justify-center px-4 py-12">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-md overflow-hidden border-slate-200 bg-white/95 shadow-2xl shadow-[#005652]/10 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <CardHeader className="border-b border-slate-200 pb-6 dark:border-slate-800">
          <InstitutionalBrand />
          <CardTitle className="mt-4 text-slate-950 dark:text-white">
            {sent ? "Correo enviado" : "Recuperar contraseña"}
          </CardTitle>
          <CardDescription>
            {sent
              ? "Si el correo existe, recibirás un enlace para restablecer tu contraseña."
              : "Ingresá tu correo electrónico y te enviaremos un enlace para restablecer tu contraseña."}
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-6">
          {sent ? (
            <div className="flex flex-col items-center gap-4 py-4 text-center">
              <CheckCircle className="h-12 w-12 text-[#00b3af]" />
              <p className="text-sm text-slate-600 dark:text-slate-400">
                Revisá tu bandeja de entrada. Si no encontrás el correo, revisá la carpeta de spam.
              </p>
              <Link href="/login" className="mt-2 text-sm font-semibold text-[#006b66] hover:text-[#004945] dark:text-[#74ddd8]">
                <ArrowLeft className="mr-1 inline h-4 w-4" />
                Volver al inicio de sesión
              </Link>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="space-y-4">
              <div>
                <label htmlFor="email" className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                  Correo electrónico
                </label>
                <Input
                  id="email"
                  type="email"
                  placeholder="consultor@ejemplo.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                />
              </div>
              {error && (
                <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
              )}
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Enviando..." : "Enviar enlace"}
              </Button>
              <div className="text-center">
                <Link href="/login" className="text-sm font-semibold text-[#006b66] hover:text-[#004945] dark:text-[#74ddd8]">
                  <ArrowLeft className="mr-1 inline h-4 w-4" />
                  Volver
                </Link>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
