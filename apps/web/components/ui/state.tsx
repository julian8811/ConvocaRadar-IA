import { AlertCircle, Loader2 } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

export function LoadingState({ label = "Cargando datos" }: { label: string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-8 text-sm text-slate-500 dark:text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        {label}
      </CardContent>
    </Card>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <Card>
      <CardContent className="py-8">
        <p className="text-sm font-medium text-slate-950 dark:text-white">{title}</p>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{detail}</p>
      </CardContent>
    </Card>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <Card className="border-destructive/30">
      <CardContent className="flex items-start gap-3 py-8 text-sm">
        <AlertCircle className="mt-0.5 h-4 w-4 text-destructive" />
        <div>
          <p className="font-medium text-destructive">No se pudo cargar la información</p>
          <p className="mt-1 text-slate-600 dark:text-slate-400">{message}</p>
        </div>
      </CardContent>
    </Card>
  );
}
