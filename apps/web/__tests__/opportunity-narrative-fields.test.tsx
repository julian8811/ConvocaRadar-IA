/**
 * PR5 (025-scraper-full-mapping): Narrative fields on opportunity detail.
 * Spec: description, open_date, eligible_applicants, evaluation_criteria,
 * restrictions — visible when populated; empty-safe when null/empty.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { OpportunityNarrativeFields } from "@/components/opportunities/OpportunityNarrativeFields";
import type { Opportunity } from "@/lib/types";

afterEach(() => {
  cleanup();
});

function narrativeOpportunity(overrides: Partial<Opportunity> = {}): Pick<
  Opportunity,
  | "description"
  | "open_date"
  | "eligible_applicants"
  | "evaluation_criteria"
  | "restrictions"
> {
  return {
    description: "",
    open_date: null,
    eligible_applicants: [],
    evaluation_criteria: [],
    restrictions: [],
    ...overrides,
  };
}

describe("OpportunityNarrativeFields — populated", () => {
  it("renders description, open_date, and the three narrative lists when set", () => {
    const fields = narrativeOpportunity({
      description: "Convocatoria para proyectos de I+D en salud.",
      open_date: "2026-01-15T12:00:00Z",
      eligible_applicants: ["Universidades", "Centros de investigación"],
      evaluation_criteria: ["Impacto social", "Viabilidad técnica"],
      restrictions: ["No aplica a personas naturales"],
    });

    render(<OpportunityNarrativeFields {...fields} />);

    expect(screen.getByText("Convocatoria para proyectos de I+D en salud.")).toBeDefined();
    expect(screen.getByText(/Apertura:\s*15\/0?1\/2026/)).toBeDefined();
    expect(screen.getByText("Universidades")).toBeDefined();
    expect(screen.getByText("Centros de investigación")).toBeDefined();
    expect(screen.getByText("Impacto social")).toBeDefined();
    expect(screen.getByText("Viabilidad técnica")).toBeDefined();
    expect(screen.getByText("No aplica a personas naturales")).toBeDefined();
    expect(screen.getByText("Elegibles")).toBeDefined();
    expect(screen.getByText("Criterios de evaluación")).toBeDefined();
    expect(screen.getByText("Restricciones")).toBeDefined();
  });
});

describe("OpportunityNarrativeFields — empty-safe", () => {
  it("renders without error and shows empty copy when narrative fields are empty", () => {
    render(<OpportunityNarrativeFields {...narrativeOpportunity()} />);

    expect(screen.getByText(/sin descripción disponible/i)).toBeDefined();
    expect(screen.getByText(/sin fecha de apertura/i)).toBeDefined();
    expect(screen.getByText(/no se han identificado elegibles/i)).toBeDefined();
    expect(screen.getByText(/no se han identificado criterios/i)).toBeDefined();
    expect(screen.getByText(/no se han identificado restricciones/i)).toBeDefined();
  });

  it("renders a second populated case with different narrative values", () => {
    render(
      <OpportunityNarrativeFields
        description="Fondo de innovación regional."
        open_date="2025-06-20T12:00:00Z"
        eligible_applicants={["Mipymes"]}
        evaluation_criteria={["Escalabilidad"]}
        restrictions={["Solo LatAm"]}
      />,
    );

    expect(screen.getByText("Fondo de innovación regional.")).toBeDefined();
    expect(screen.getByText(/Apertura:\s*20\/0?6\/2025/)).toBeDefined();
    expect(screen.getByText("Mipymes")).toBeDefined();
    expect(screen.getByText("Escalabilidad")).toBeDefined();
    expect(screen.getByText("Solo LatAm")).toBeDefined();
  });
});

describe("Opportunity type — narrative fields", () => {
  it("accepts the five narrative fields on Opportunity", () => {
    const opp = {
      description: "Full body",
      open_date: "2026-03-01T00:00:00Z",
      eligible_applicants: ["ONG"],
      evaluation_criteria: ["Mérito"],
      restrictions: ["Tope presupuestal"],
    } satisfies Pick<
      Opportunity,
      | "description"
      | "open_date"
      | "eligible_applicants"
      | "evaluation_criteria"
      | "restrictions"
    >;

    expect(opp.description).toBe("Full body");
    expect(opp.open_date).toBe("2026-03-01T00:00:00Z");
    expect(opp.eligible_applicants).toEqual(["ONG"]);
    expect(opp.evaluation_criteria).toEqual(["Mérito"]);
    expect(opp.restrictions).toEqual(["Tope presupuestal"]);
  });
});
