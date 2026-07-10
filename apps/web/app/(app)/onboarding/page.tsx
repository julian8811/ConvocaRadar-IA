"use client";

import { Save, Info } from "lucide-react";
import React, { FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";

const ORG_TYPES = [
  { value: "university", label: "Universidad" },
  { value: "research_center", label: "Centro de investigación" },
  { value: "company", label: "Empresa" },
  { value: "ngo", label: "ONG / Fundación" },
  { value: "government", label: "Entidad gubernamental" },
  { value: "other", label: "Otra" },
];

const CAPACITY_OPTIONS = [
  { value: "low", label: "Baja — 1-2 convocatorias por mes", description: "Equipo pequeño, postulación selectiva" },
  { value: "medium", label: "Media — 3-5 convocatorias por mes", description: "Equipo dedicado, postulación regular" },
  { value: "high", label: "Alta — 6+ convocatorias por mes", description: "Equipo amplio, postulación frecuente" },
];

const SUGGESTED_AREAS = [
  "innovación", "emprendimiento", "investigación", "educación",
  "ciencia y tecnología", "medio ambiente", "cultura", "salud",
  "inclusión social", "derechos humanos", "desarrollo sostenible",
  "energía", "agricultura", "transformación digital",
];

const SUGGESTED_FUNDING = ["grant", "cofinancing", "scholarship", "loan", "award", "equity", "technical_assistance"];

const FUNDING_LABELS: Record<string, string> = {
  grant: "Subvención / Grant",
  cofinancing: "Cofinanciación",
  scholarship: "Beca",
  loan: "Préstamo",
  award: "Premio / Reconocimiento",
  equity: "Capital / Inversión",
  technical_assistance: "Asistencia técnica",
};

const SUGGESTED_CURRENCIES = ["COP", "USD", "EUR", "GBP", "BRL", "MXN", "CLP", "PEN"];

function TagSelector({
  label,
  options,
  selected,
  onChange,
  emptyLabel,
}: {
  label: string;
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (values: string[]) => void;
  emptyLabel?: string;
}) {
  const available = options.filter((o) => !selected.includes(o.value));
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium text-slate-700 dark:text-slate-300">{label}</label>
      {selected.length === 0 && emptyLabel && (
        <p className="text-xs text-slate-400">{emptyLabel}</p>
      )}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => onChange(selected.filter((v) => v !== value))}
              className="inline-flex items-center gap-1 rounded-full bg-cyan-50 px-3 py-1 text-xs font-medium text-cyan-700 hover:bg-cyan-100 dark:bg-cyan-400/10 dark:text-cyan-200 dark:hover:bg-cyan-400/20"
            >
              {options.find((o) => o.value === value)?.label ?? value}
              <span className="text-cyan-400">&times;</span>
            </button>
          ))}
        </div>
      )}
      {available.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {available.slice(0, 8).map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange([...selected, option.value])}
              className="inline-flex items-center rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-500 hover:border-cyan-200 hover:text-cyan-700 dark:border-slate-700 dark:text-slate-400 dark:hover:border-cyan-400/30 dark:hover:text-cyan-200"
            >
              + {option.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function OnboardingPage() {
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const organization = useQuery({ queryKey: ["organization"], queryFn: api.organization });
  const save = useMutation({
    mutationFn: api.updateProfile,
    onSuccess: () => toast.success("Perfil institucional actualizado"),
  });

  const profileData = profile.data ?? {};
  const orgData = organization.data ?? {};

  // Hooks must be called unconditionally — before any early return
  const [areas, setAreas] = React.useState<string[]>(Array.isArray(profileData.areas_of_interest) ? profileData.areas_of_interest : []);
  const [fundingTypes, setFundingTypes] = React.useState<string[]>(Array.isArray(profileData.funding_types) ? profileData.funding_types : []);
  const [currencies, setCurrencies] = React.useState<string[]>(Array.isArray(profileData.preferred_currencies) ? profileData.preferred_currencies : ["COP", "USD"]);
  const [regions, setRegions] = React.useState<string[]>(Array.isArray(profileData.regions_of_interest) ? profileData.regions_of_interest : ["LatAm"]);

  if (profile.isLoading || organization.isLoading) return <LoadingState label="Cargando perfil" />;
  if (profile.error) return <ErrorState message={profile.error.message} />;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);

    save.mutate({
      description: form.get("description") || `${orgData.name} — ${orgData.country}`,
      country: form.get("country") || orgData.country || "Colombia",
      organization_type: form.get("organization_type") || "university",
      areas_of_interest: JSON.parse(String(form.get("_areas_of_interest") || "[]")),
      funding_types: JSON.parse(String(form.get("_funding_types") || "[]")),
      regions_of_interest: JSON.parse(String(form.get("_regions_of_interest") || "[]")),
      preferred_currencies: JSON.parse(String(form.get("_preferred_currencies") || "[]")),
      min_funding_amount: Number(form.get("min_funding_amount")) || undefined,
      max_funding_amount: Number(form.get("max_funding_amount")) || undefined,
      eligible_international: form.get("eligible_international") === "true",
      languages: ["es", "en"],
      application_capacity: form.get("application_capacity") || "medium",
    });
  }

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Perfil institucional</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
          El sistema compara cada convocatoria contra este perfil para calcular el score de compatibilidad.
          Completalo con cuidado — define qué convocatorias te van a aparecer como prioritarias.
        </p>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        {/* Organización */}
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Info className="h-4 w-4 text-cyan-600" />
              Organización
            </CardTitle>
            <CardDescription>Datos base de tu entidad.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-5">
            <div>
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Nombre</label>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{String(orgData.name ?? "")}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">País</label>
              <Input
                name="country"
                defaultValue={String(profileData.country || orgData.country || "Colombia")}
                placeholder="Colombia"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Tipo de organización</label>
              <select
                name="organization_type"
                defaultValue={String(profileData.organization_type || "university")}
                className="mt-1 flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-cyan-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              >
                {ORG_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Descripción</label>
              <Input
                name="description"
                defaultValue={String(profileData.description || "")}
                placeholder="Ej: Centro de investigación en biotecnología"
              />
              <p className="mt-1 text-xs text-slate-400">Breve descripción de tu organización.</p>
            </div>
          </CardContent>
        </Card>

        {/* Capacidad y financiamiento */}
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Info className="h-4 w-4 text-cyan-600" />
              Capacidad y financiamiento
            </CardTitle>
            <CardDescription>Tu capacidad de postulación y rangos de interés.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-5">
            <div>
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Capacidad de postulación</label>
              <select
                name="application_capacity"
                defaultValue={String(profileData.application_capacity || "medium")}
                className="mt-1 flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-cyan-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              >
                {CAPACITY_OPTIONS.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
              <p className="mt-1 text-xs text-slate-400">
                {CAPACITY_OPTIONS.find((c) => c.value === (profileData.application_capacity || "medium"))?.description}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Monto mínimo (USD)</label>
                <Input
                  name="min_funding_amount"
                  type="number"
                  defaultValue={profileData.min_funding_amount ?? ""}
                  placeholder="Ej: 50000"
                />
              </div>
              <div>
                <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Monto máximo (USD)</label>
                <Input
                  name="max_funding_amount"
                  type="number"
                  defaultValue={profileData.max_funding_amount ?? ""}
                  placeholder="Ej: 500000"
                />
              </div>
            </div>
            <div>
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Elegible para convocatorias internacionales</label>
              <select
                name="eligible_international"
                defaultValue={String(profileData.eligible_international ?? true)}
                className="mt-1 flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-cyan-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              >
                <option value="true">Sí</option>
                <option value="false">No</option>
              </select>
            </div>
          </CardContent>
        </Card>

        {/* Áreas de interés */}
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Info className="h-4 w-4 text-cyan-600" />
              Áreas de interés
            </CardTitle>
            <CardDescription>Seleccioná las áreas donde tu organización busca financiamiento.</CardDescription>
          </CardHeader>
          <CardContent className="pt-5">
            <input type="hidden" name="_areas_of_interest" value={JSON.stringify(areas)} />
            <TagSelector
              label=""
              options={SUGGESTED_AREAS.map((a) => ({ value: a, label: a.charAt(0).toUpperCase() + a.slice(1) }))}
              selected={areas}
              onChange={setAreas}
              emptyLabel="Hacé clic en las áreas que te interesen"
            />
          </CardContent>
        </Card>

        {/* Tipos de financiamiento + Monedas */}
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Info className="h-4 w-4 text-cyan-600" />
              Financiamiento y monedas
            </CardTitle>
            <CardDescription>Tipos de financiamiento que buscás y monedas que manejás.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5 pt-5">
            <input type="hidden" name="_funding_types" value={JSON.stringify(fundingTypes)} />
            <TagSelector
              label="Tipos de financiamiento"
              options={SUGGESTED_FUNDING.map((f) => ({ value: f, label: FUNDING_LABELS[f] || f }))}
              selected={fundingTypes}
              onChange={setFundingTypes}
              emptyLabel="Seleccioná los tipos que te interesen"
            />
            <div>
              <input type="hidden" name="_preferred_currencies" value={JSON.stringify(currencies)} />
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Monedas</label>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {SUGGESTED_CURRENCIES.map((c) => {
                  const active = currencies.includes(c);
                  return (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setCurrencies(active ? currencies.filter((v) => v !== c) : [...currencies, c])}
                      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                        active
                          ? "bg-cyan-50 text-cyan-700 dark:bg-cyan-400/10 dark:text-cyan-200"
                          : "border border-slate-200 text-slate-500 hover:border-cyan-200 dark:border-slate-700 dark:text-slate-400"
                      }`}
                    >
                      {c}
                    </button>
                  );
                })}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Regiones */}
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
            <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
              <Info className="h-4 w-4 text-cyan-600" />
              Regiones de interés
            </CardTitle>
            <CardDescription>Regiones geográficas donde buscás oportunidades.</CardDescription>
          </CardHeader>
          <CardContent className="pt-5">
            <input type="hidden" name="_regions_of_interest" value={JSON.stringify(regions)} />
            {["LatAm", "Europa", "África", "Asia", "Norteamérica", "Oceanía", "Global"].map((r) => {
              const active = regions.includes(r);
              return (
                <button
                  key={r}
                  type="button"
                  onClick={() => setRegions(active ? regions.filter((v) => v !== r) : [...regions, r])}
                  className={`mb-1.5 mr-1.5 inline-flex items-center rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                    active
                      ? "bg-cyan-50 text-cyan-700 dark:bg-cyan-400/10 dark:text-cyan-200"
                      : "border border-slate-200 text-slate-500 hover:border-cyan-200 dark:border-slate-700 dark:text-slate-400"
                  }`}
                >
                  {r}
                </button>
              );
            })}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="pt-5">
          <Button
            className="w-full"
            disabled={save.isPending}
            onClick={() => {
              const form = document.querySelector("form");
              if (form) form.requestSubmit();
            }}
          >
            <Save className="h-4 w-4" />
            {save.isPending ? "Guardando..." : "Guardar perfil"}
          </Button>
        </CardContent>
      </Card>

      {/* Hidden form to collect all data on submit */}
      <form onSubmit={submit} className="hidden" />
    </section>
  );
}
