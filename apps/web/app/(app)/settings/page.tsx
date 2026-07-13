"use client";

import { Database, LockKeyhole, Mail, PlugZap, ShieldCheck, Building2, MapPin, Globe, Tags, Coins, Users, GraduationCap, Briefcase } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { API_URL, api } from "@/lib/api";
import type { Organization, OrganizationProfile } from "@/lib/types";

function OrgInfo({ org, profile }: { org: Organization; profile: OrganizationProfile }) {
  const infoItems = [
    { icon: Building2, label: "Organización", value: org.name },
    { icon: MapPin, label: "País", value: org.country || profile.country },
    { icon: Globe, label: "Sitio web", value: org.website || "—" },
    { icon: Tags, label: "Tipo", value: profile.organization_type || org.type },
    { icon: Users, label: "Áreas de interés", value: profile.areas_of_interest?.join(", ") || "—" },
    { icon: Coins, label: "Tipos de financiamiento", value: profile.funding_types?.join(", ") || "—" },
    { icon: Briefcase, label: "Capacidad de aplicación", value: profile.application_capacity || "—" },
  ];

  return (
    <Card>
      <CardHeader className="border-b border-slate-200 pb-4 dark:border-slate-700">
        <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
          <Building2 className="h-4 w-4" />
          Organización
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 pt-5 sm:grid-cols-2 xl:grid-cols-3">
        {infoItems.map((item) => {
          const Icon = item.icon;
          return (
            <div key={item.label} className="flex items-start gap-3 rounded-md border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
              <div className="min-w-0">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{item.label}</p>
                <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white truncate">{item.value}</p>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

const OPERATIONAL_CARDS = [
  { icon: Database, title: "API", value: API_URL },
  { icon: LockKeyhole, title: "Seguridad", value: "JWT, permisos por organización y protección SSRF" },
  { icon: Mail, title: "Alertas", value: "SMTP configurable; la ejecución local registra alertas sin correo real" },
  { icon: PlugZap, title: "Scraping", value: "Motor híbrido con conectores dedicados, reintentos y health checks" },
  { icon: ShieldCheck, title: "Auditoría", value: "Acciones sensibles registradas en logs y eventos administrativos" },
];

export default function SettingsPage() {
  const org = useQuery<Organization>({
    queryKey: ["organization"],
    queryFn: () => api.organization() as Promise<Organization>,
  });

  const profile = useQuery<OrganizationProfile>({
    queryKey: ["profile"],
    queryFn: () => api.profile() as Promise<OrganizationProfile>,
  });

  if (org.isLoading || profile.isLoading) return <LoadingState label="Cargando configuración" />;
  if (org.error) return <ErrorState message={org.error.message} />;

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Configuración</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
          Datos de la organización y configuración operativa del sistema.
        </p>
      </div>

      {org.data && profile.data && <OrgInfo org={org.data} profile={profile.data} />}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {OPERATIONAL_CARDS.map((item) => {
          const Icon = item.icon;
          return (
            <Card key={item.title}>
              <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
                <CardTitle className="flex items-center gap-2 text-base text-slate-950 dark:text-white">
                  <Icon className="h-4 w-4" />
                  {item.title}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 pt-5 text-sm text-slate-700 dark:text-slate-300">
                <p>{item.value}</p>
                <Badge tone="muted">Configuración activa</Badge>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </section>
  );
}
