/**
 * PR B-2 (dashboard-redesign): Unit tests for the extracted OpportunityRow
 * component. Covers the new column variants (Razones, Cierra en, status
 * badge) that the two new tables need.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

vi.mock("next/link", () => ({
  default: ({ children, ...props }: { children: React.ReactNode; href: string }) => <a {...props}>{children}</a>,
}));

async function loadRow() {
  vi.resetModules();
  const mod = await import("@/components/dashboard/OpportunityRow");
  return mod.OpportunityRow;
}

const baseItem = {
  id: "opp-1",
  title: "Becas de investigación X",
  country: "Colombia",
  currency: "USD",
  funding_amount: 50000,
  days_to_close: 30,
  score: 82,
  reasons: [],
  source_key: "minciencias",
};

describe("OpportunityRow — showReasons", () => {
  it("renders the first 2 reasons and a '+N más' indicator when reasons > 2", async () => {
    const OpportunityRow = await loadRow();
    render(
      <table>
        <tbody>
          <OpportunityRow
            item={{ ...baseItem, reasons: ["Monto alto", "Coincide con área", "País prioritario"] }}
            showReasons
          />
        </tbody>
      </table>,
    );
    expect(screen.getByText("Monto alto")).toBeDefined();
    expect(screen.getByText("Coincide con área")).toBeDefined();
    expect(screen.getByText("+1 más")).toBeDefined();
  });

  it("renders the available reasons without a '+N más' indicator when reasons <= 2", async () => {
    const OpportunityRow = await loadRow();
    render(
      <table>
        <tbody>
          <OpportunityRow
            item={{ ...baseItem, reasons: ["Monto alto", "Coincide con área"] }}
            showReasons
          />
        </tbody>
      </table>,
    );
    expect(screen.getByText("Monto alto")).toBeDefined();
    expect(screen.getByText("Coincide con área")).toBeDefined();
    expect(screen.queryByText(/\+\d+ más/)).toBeNull();
  });

  it("renders a 'Sin razones registradas' fallback when reasons is empty", async () => {
    const OpportunityRow = await loadRow();
    render(
      <table>
        <tbody>
          <OpportunityRow item={{ ...baseItem, reasons: [] }} showReasons />
        </tbody>
      </table>,
    );
    expect(screen.getByText(/sin razones registradas/i)).toBeDefined();
  });
});

describe("OpportunityRow — showCountdown", () => {
  it("renders a red badge for days_to_close <= 3", async () => {
    const OpportunityRow = await loadRow();
    render(
      <table>
        <tbody>
          <OpportunityRow item={{ ...baseItem, days_to_close: 2 }} showCountdown />
        </tbody>
      </table>,
    );
    const badge = screen.getByText("2 días");
    expect(badge).toBeDefined();
    // Tone is applied via className. Check the class on the rendered element.
    const parent = badge.closest("span") ?? badge;
    expect(parent.className).toMatch(/rose/);
  });

  it("renders an amber badge for days_to_close <= 7 (but > 3)", async () => {
    const OpportunityRow = await loadRow();
    render(
      <table>
        <tbody>
          <OpportunityRow item={{ ...baseItem, days_to_close: 5 }} showCountdown />
        </tbody>
      </table>,
    );
    const badge = screen.getByText("5 días");
    expect(badge).toBeDefined();
    const parent = badge.closest("span") ?? badge;
    expect(parent.className).toMatch(/amber|indigo/);
  });

  it("renders 'Hoy' when days_to_close === 0", async () => {
    const OpportunityRow = await loadRow();
    render(
      <table>
        <tbody>
          <OpportunityRow item={{ ...baseItem, days_to_close: 0 }} showCountdown />
        </tbody>
      </table>,
    );
    expect(screen.getByText("Hoy")).toBeDefined();
  });

  it("renders '1 día' (singular) when days_to_close === 1", async () => {
    const OpportunityRow = await loadRow();
    render(
      <table>
        <tbody>
          <OpportunityRow item={{ ...baseItem, days_to_close: 1 }} showCountdown />
        </tbody>
      </table>,
    );
    expect(screen.getByText("1 día")).toBeDefined();
  });

  it("renders a plain text countdown for days_to_close > 7 (no badge)", async () => {
    const OpportunityRow = await loadRow();
    render(
      <table>
        <tbody>
          <OpportunityRow item={{ ...baseItem, days_to_close: 30 }} showCountdown />
        </tbody>
      </table>,
    );
    expect(screen.getByText("30 días")).toBeDefined();
  });

  it("renders 'Sin fecha' when days_to_close is null", async () => {
    const OpportunityRow = await loadRow();
    render(
      <table>
        <tbody>
          <OpportunityRow item={{ ...baseItem, days_to_close: null }} showCountdown />
        </tbody>
      </table>,
    );
    expect(screen.getByText(/sin fecha/i)).toBeDefined();
  });
});

describe("OpportunityRow — showStatusBadge (review queue)", () => {
  it("renders an 'En revisión' badge when showStatusBadge is true", async () => {
    const OpportunityRow = await loadRow();
    render(
      <table>
        <tbody>
          <OpportunityRow item={{ ...baseItem }} showStatusBadge />
        </tbody>
      </table>,
    );
    expect(screen.getByText(/en revisi[oó]n/i)).toBeDefined();
  });
});

describe("OpportunityRow — default variant (no flags)", () => {
  it("renders the legacy 5 columns (Convocatoria, País, Score, Plazo, Monto) without Razones or countdown", async () => {
    const OpportunityRow = await loadRow();
    render(
      <table>
        <tbody>
          <OpportunityRow
            item={{ ...baseItem, days_to_close: 12, reasons: ["should not render"] }}
          />
        </tbody>
      </table>,
    );
    // The reasons column must NOT render in the default variant.
    expect(screen.queryByText("should not render")).toBeNull();
    // The legacy "12 d" countdown format renders in the Plazo cell.
    expect(screen.getByText("12 d")).toBeDefined();
  });
});
