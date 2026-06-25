"use client";

import { Save } from "lucide-react";
import { FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";

export default function OnboardingPage() {
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const save = useMutation({
    mutationFn: api.updateProfile,
    onSuccess: () => toast.success("Perfil institucional actualizado"),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);

    save.mutate({
      description: form.get("description"),
      country: form.get("country"),
      organization_type: form.get("organization_type"),
      areas_of_interest: String(form.get("areas_of_interest"))
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      funding_types: String(form.get("funding_types"))
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      preferred_currencies: String(form.get("preferred_currencies"))
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      eligible_international: true,
      languages: ["es", "en"],
      application_capacity: form.get("application_capacity"),
    });
  }

  if (profile.isLoading) return <LoadingState label="Cargando perfil" />;
  if (profile.error) return <ErrorState message={profile.error.message} />;
  const profileData = profile.data ?? {};

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Perfil institucional</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
          El scoring compara cada convocatoria contra este perfil para calcular compatibilidad y prioridad.
        </p>
      </div>
      <Card>
        <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
          <CardTitle className="text-slate-950 dark:text-white">Datos de compatibilidad</CardTitle>
          <CardDescription>Usa listas separadas por coma para áreas, financiación y monedas.</CardDescription>
        </CardHeader>
        <CardContent className="pt-5">
          <form className="grid gap-4 md:grid-cols-2" onSubmit={submit}>
            <Input name="description" placeholder="Descripción" defaultValue={String(profileData.description ?? "")} />
            <Input name="country" placeholder="País" defaultValue={String(profileData.country ?? "Colombia")} />
            <Input
              name="organization_type"
              placeholder="Tipo de organización"
              defaultValue={String(profileData.organization_type ?? "university")}
            />
            <Input name="application_capacity" placeholder="Capacidad: low, medium, high" defaultValue={String(profileData.application_capacity ?? "medium")} />
            <Input
              name="areas_of_interest"
              placeholder="Áreas de interés"
              defaultValue={Array.isArray(profileData.areas_of_interest) ? profileData.areas_of_interest.join(", ") : ""}
            />
            <Input
              name="funding_types"
              placeholder="Tipos de financiación"
              defaultValue={Array.isArray(profileData.funding_types) ? profileData.funding_types.join(", ") : ""}
            />
            <Input
              name="preferred_currencies"
              placeholder="Monedas"
              defaultValue={Array.isArray(profileData.preferred_currencies) ? profileData.preferred_currencies.join(", ") : "COP, USD"}
            />
            <Button className="md:col-span-2" disabled={save.isPending}>
              <Save className="h-4 w-4" />
              Guardar perfil
            </Button>
          </form>
        </CardContent>
      </Card>
    </section>
  );
}
