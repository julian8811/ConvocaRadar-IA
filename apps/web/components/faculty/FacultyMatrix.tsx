"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/state";
import { api } from "@/lib/api";

type Cell = { faculty_id: string; axis_id: string; count: number };

export function FacultyMatrix() {
  const faculties = useQuery({ queryKey: ["faculties"], queryFn: () => api.faculties() });
  const axes = useQuery({ queryKey: ["axes"], queryFn: () => api.axes() });
  const matrix = useQuery({ queryKey: ["faculty-matrix"], queryFn: () => api.facultyMatrix() });

  const facList = (faculties.data as any)?.faculties ?? [];
  const axisList = (axes.data as any)?.axes ?? [];
  const dimsLabel = `${facList.length}×${axisList.length}`;

  if (faculties.isLoading || axes.isLoading || matrix.isLoading) {
    return <Card><CardContent className="p-6">Cargando matriz…</CardContent></Card>;
  }
  const firstError = faculties.error ?? axes.error ?? matrix.error;
  if (firstError) {
    return <ErrorState message={firstError instanceof Error ? firstError.message : "No se pudo cargar la matriz"} />;
  }
  const cells: Cell[] = (matrix.data as any)?.cells ?? [];
  const maxCount = Math.max(1, ...cells.map((c) => c.count));

  // R3: sin matching ejecutado (todo en 0) la matriz es decorativa → empty-state.
  if (cells.length === 0 || cells.every((c) => c.count === 0)) {
    return (
      <Card>
        <CardHeader><CardTitle>Matriz Facultades × Ejes ({dimsLabel})</CardTitle></CardHeader>
        <CardContent className="p-6">
          <EmptyState title="Matching aún no ejecutado" detail="Ejecutá el matching facultad × eje para ver la distribución de oportunidades." />
        </CardContent>
      </Card>
    );
  }

  const getCount = (fid: string, aid: string) => cells.find((c) => c.faculty_id === fid && c.axis_id === aid)?.count ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Matriz Facultades × Ejes ({dimsLabel})</CardTitle>
        <CardDescription>Distribución de matches por facultad y eje institucional.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr>
                  <th className="p-2 text-left">Eje / Facultad</th>
                  {facList.map((f: any) => (
                    <th key={f.id} className="p-2 text-center" style={{ color: f.color }}>{f.key}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {axisList.map((ax: any) => (
                  <tr key={ax.id}>
                    <td className="p-2 font-medium">{ax.label}</td>
                    {facList.map((f: any) => {
                      const count = getCount(f.id, ax.id);
                      const intensity = count / maxCount;
                      const bg = `rgba(14,116,144,${0.15 + intensity * 0.85})`;
                      return (
                        <td key={f.id} className="p-1">
                          <div title={`${f.key} × ${ax.label}: ${count} oportunidades`} className="h-10 w-full rounded-md flex items-center justify-center text-xs font-semibold cursor-pointer" style={{ backgroundColor: count ? bg : "#f1f5f9", color: count ? "white" : "#64748b" }}>
                            {count}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
      </CardContent>
    </Card>
  );
}
