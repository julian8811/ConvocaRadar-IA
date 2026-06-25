"use client";

import { Bell, BellOff, Pause, Play, Send, Trash2 } from "lucide-react";
import { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardDescription, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { Alert } from "@/lib/types";

const alertTypes = [
  { value: "new_opportunity", label: "Nueva oportunidad" },
  { value: "high_compatibility", label: "Alta compatibilidad" },
  { value: "closing_soon", label: "Cierre próximo" },
  { value: "weekly_digest", label: "Resumen semanal" },
];

function statusTone(status: string) {
  if (status === "sent") return "open";
  if (status === "paused") return "closed";
  if (status === "failed") return "not_recommended";
  return "closing_soon";
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    pending: "Pendiente",
    paused: "Pausada",
    sent: "Enviada",
    failed: "Fallida",
  };
  return map[status] ?? status;
}

function alertTypeLabel(value: string) {
  return alertTypes.find((item) => item.value === value)?.label ?? value;
}

function AlertCard({ alert }: { alert: Alert }) {
  const queryClient = useQueryClient();
  const updateAlert = useMutation({
    mutationFn: (status: string) => api.updateAlert(alert.id, { status }),
    onSuccess: () => {
      toast.success("Alerta actualizada");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo actualizar"),
  });

  const deleteAlert = useMutation({
    mutationFn: () => api.deleteAlert(alert.id),
    onSuccess: () => {
      toast.success("Alerta eliminada");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo eliminar"),
  });

  const sendAlert = useMutation({
    mutationFn: () => api.sendAlert(alert.id),
    onSuccess: () => {
      toast.success("Alerta enviada");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo enviar"),
  });

  const isPaused = alert.status === "paused";

  return (
    <Card>
      <CardContent className="flex gap-4 p-5">
        {isPaused ? <BellOff className="mt-1 h-5 w-5 text-slate-500 dark:text-slate-400" /> : <Bell className="mt-1 h-5 w-5 text-cyan-600 dark:text-cyan-200" />}
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="font-medium text-slate-950 dark:text-white">{alert.subject}</p>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {alert.recipient} · {alert.channel} · {alertTypeLabel(alert.alert_type)}
              </p>
            </div>
            <Badge tone={statusTone(alert.status)}>{statusLabel(alert.status)}</Badge>
          </div>
          <p className="text-sm text-slate-700 dark:text-slate-300">{alert.message}</p>
          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Creada {new Date(alert.created_at).toLocaleString("es-CO")}
              {alert.sent_at ? ` · enviada ${new Date(alert.sent_at).toLocaleString("es-CO")}` : ""}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="icon"
                title={isPaused ? "Reactivar" : "Pausar"}
                disabled={updateAlert.isPending}
                onClick={() => updateAlert.mutate(isPaused ? "pending" : "paused")}
              >
                {isPaused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
              </Button>
              <Button
                variant="outline"
                size="icon"
                title="Enviar ahora"
                disabled={sendAlert.isPending || alert.status === "sent" || alert.status === "paused"}
                onClick={() => sendAlert.mutate()}
              >
                <Send className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="icon" title="Eliminar" disabled={deleteAlert.isPending} onClick={() => deleteAlert.mutate()}>
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function AlertsPage() {
  const queryClient = useQueryClient();
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts });
  const createAlert = useMutation({
    mutationFn: api.createAlert,
    onSuccess: () => {
      toast.success("Alerta creada");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo crear la alerta"),
  });
  const testAlert = useMutation({
    mutationFn: api.testAlert,
    onSuccess: () => {
      toast.success("Alerta de prueba enviada");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudo registrar la prueba"),
  });
  const generateAlerts = useMutation({
    mutationFn: api.generateAlerts,
    onSuccess: (items) => {
      toast.success(items.length ? `${items.length} alertas sugeridas creadas` : "No hay alertas nuevas sugeridas");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "No se pudieron generar alertas"),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    createAlert.mutate({
      alert_type: String(form.get("alert_type")),
      channel: "email",
      recipient: String(form.get("recipient")),
      subject: String(form.get("subject")),
      message: String(form.get("message")),
      scheduled_at: form.get("scheduled_at") ? String(form.get("scheduled_at")) : null,
    });
    event.currentTarget.reset();
  }

  function submitTest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    testAlert.mutate(String(form.get("recipient")));
    event.currentTarget.reset();
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">Alertas</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            Correos auditables para novedades, cierres próximos y oportunidades de alta compatibilidad.
          </p>
        </div>
        <Button variant="outline" disabled={generateAlerts.isPending} onClick={() => generateAlerts.mutate()}>
          <Bell className="h-4 w-4" />
          Generar sugeridas
        </Button>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHeader className="border-b border-border/70 pb-4">
            <CardTitle className="text-slate-950 dark:text-white">Nueva alerta</CardTitle>
            <CardDescription>Configura el canal y el mensaje auditable.</CardDescription>
          </CardHeader>
          <CardContent className="pt-5">
            <form className="grid gap-3 md:grid-cols-2" onSubmit={submit}>
              <Select name="alert_type">
                {alertTypes.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </Select>
              <Input name="recipient" type="email" placeholder="usuario@organizacion.com" required />
              <Input name="subject" placeholder="Asunto" required />
              <Input name="scheduled_at" type="datetime-local" />
              <Input name="message" placeholder="Mensaje para auditoría" className="md:col-span-2" required />
              <div className="md:col-span-2">
                <Button disabled={createAlert.isPending}>
                  <Bell className="h-4 w-4" />
                  Crear alerta
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border/70 pb-4">
            <CardTitle className="text-slate-950 dark:text-white">Prueba de correo</CardTitle>
            <CardDescription>Registra una prueba sin salir del panel.</CardDescription>
          </CardHeader>
          <CardContent className="pt-5">
            <form className="flex flex-col gap-3" onSubmit={submitTest}>
              <Input name="recipient" type="email" placeholder="usuario@organizacion.com" required />
              <Button variant="outline" disabled={testAlert.isPending}>
                <Send className="h-4 w-4" />
                Registrar prueba
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      {alerts.isLoading ? <LoadingState label="Cargando alertas" /> : null}
      {alerts.error ? <ErrorState message={alerts.error.message} /> : null}
      {alerts.data && alerts.data.length === 0 ? <EmptyState title="No hay alertas" detail="Crea una alerta o registra una prueba de correo." /> : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {(alerts.data ?? []).map((alert) => (
          <AlertCard key={alert.id} alert={alert} />
        ))}
      </div>
    </section>
  );
}
