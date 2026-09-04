"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export function ProfileEditor() {
  const qc = useQueryClient();
  const profiles = useQuery({ queryKey: ["faculty-profiles"], queryFn: () => api.facultyProfiles() });
  const [editing, setEditing] = useState<string | null>(null);
  const [thr, setThr] = useState("");
  const [color, setColor] = useState("");

  const mut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Record<string, unknown> }) => api.updateFacultyProfile(id, payload),
    onSuccess: () => {
      toast.success("Perfil actualizado");
      qc.invalidateQueries({ queryKey: ["faculty-profiles"] });
      qc.invalidateQueries({ queryKey: ["faculty-matrix"] });
      setEditing(null);
    },
    onError: (e: any) => toast.error(e.message),
  });

  if (profiles.isLoading) return <Card><CardContent className="p-6">Cargando perfiles...</CardContent></Card>;

  const list = (profiles.data as any) ?? [];
  return (
    <Card>
      <CardHeader><CardTitle>Editor perfiles por facultad (threshold, color)</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {list.map((p: any) => (
          <div key={p.id} className="flex items-center gap-3 rounded-md border p-3">
            <div className="flex-1 text-sm">
              <div className="font-medium">{p.faculty_id} × {p.axis_id}</div>
              <div className="text-xs text-muted-foreground">thr {p.threshold} v{p.version}</div>
            </div>
            {editing === p.id ? (
              <>
                <Input className="w-20" value={thr} onChange={(e) => setThr(e.target.value)} placeholder="0.35" />
                <Input className="w-24" value={color} onChange={(e) => setColor(e.target.value)} placeholder="#0e7490" />
                <Button size="sm" onClick={() => mut.mutate({ id: p.id, payload: { threshold: parseFloat(thr) || undefined, color: color || undefined } })}>Guardar</Button>
                <Button size="sm" variant="outline" onClick={() => setEditing(null)}>Cancelar</Button>
              </>
            ) : (
              <Button size="sm" variant="outline" onClick={() => { setEditing(p.id); setThr(String(p.threshold)); setColor(p.color); }}>Editar</Button>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
