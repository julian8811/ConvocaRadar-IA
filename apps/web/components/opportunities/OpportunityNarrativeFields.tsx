import { FileCheck, FileText, ShieldAlert, Users } from "lucide-react";
import type { ElementType } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { decodeVisibleText } from "@/lib/text";

export type OpportunityNarrativeFieldsProps = {
  description: string;
  open_date: string | null;
  eligible_applicants: string[];
  evaluation_criteria: string[];
  restrictions: string[];
};

function formatOpenDate(value: string | null): string {
  if (!value) return "Sin fecha de apertura";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Sin fecha de apertura";
  return parsed.toLocaleDateString("es-CO");
}

function InfoList({
  title,
  icon: Icon,
  items,
  empty,
}: {
  title: string;
  icon: ElementType;
  items: string[];
  empty: string;
}) {
  return (
    <Card>
      <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
        <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
          <Icon className="h-4 w-4" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-5">
        {items.length ? (
          <ul className="space-y-2 text-sm text-slate-700 dark:text-slate-300">
            {items.map((item) => (
              <li key={item} className="rounded-lg bg-slate-100 px-3 py-2 dark:bg-slate-800">
                {item}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function OpportunityNarrativeFields({
  description,
  open_date,
  eligible_applicants,
  evaluation_criteria,
  restrictions,
}: OpportunityNarrativeFieldsProps) {
  const descriptionText = decodeVisibleText(description, "").trim();

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="border-b border-slate-200 dark:border-slate-700 pb-4">
          <CardTitle className="flex items-center gap-2 text-slate-950 dark:text-white">
            <FileText className="h-4 w-4" />
            Descripción
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 pt-5 text-sm leading-6 text-slate-700 dark:text-slate-300">
          <p>{descriptionText || "Sin descripción disponible."}</p>
          <p className="text-slate-500 dark:text-slate-400">
            Apertura: {formatOpenDate(open_date)}
          </p>
        </CardContent>
      </Card>

      <InfoList
        title="Elegibles"
        icon={Users}
        items={eligible_applicants}
        empty="No se han identificado elegibles."
      />
      <InfoList
        title="Criterios de evaluación"
        icon={FileCheck}
        items={evaluation_criteria}
        empty="No se han identificado criterios."
      />
      <InfoList
        title="Restricciones"
        icon={ShieldAlert}
        items={restrictions}
        empty="No se han identificado restricciones."
      />
    </div>
  );
}
