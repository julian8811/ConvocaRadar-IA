"use client";

import { Database, LockKeyhole, Mail, PlugZap, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { API_URL } from "@/lib/api";

export default function SettingsPage() {
  const settings = [
    { icon: Database, title: "API", value: API_URL },
    { icon: LockKeyhole, title: "Seguridad", value: "JWT, permisos por organización y protección SSRF" },
    { icon: Mail, title: "Alertas", value: "SMTP configurable; la ejecución local registra alertas sin correo real" },
    { icon: PlugZap, title: "Scraping", value: "Motor híbrido con conectores dedicados, reintentos y health checks" },
    { icon: ShieldCheck, title: "Auditoría", value: "Acciones sensibles registradas en logs y eventos administrativos" },
  ];

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Configuración</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
          Variables operativas y decisiones activas del MVP.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {settings.map((item) => {
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
                <Badge tone="medium">Configuración activa</Badge>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </section>
  );
}
