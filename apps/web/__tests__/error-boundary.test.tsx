/**
 * REQ-FE-BOUNDARY-1 — Route-level error boundaries.
 *
 * Next.js wraps every route segment with its runtime error boundary and
 * hands the caught render-time error to the segment's `error.tsx` client
 * component together with a `reset()` callback. These tests pin that
 * contract for the three boundaries introduced in PR3:
 *
 * - apps/web/app/error.tsx          (root segment)
 * - apps/web/app/(app)/error.tsx    (dashboard route group: dashboard,
 *                                    admin, opportunities, alerts, reports,
 *                                    settings, sources, onboarding)
 * - apps/web/app/global-error.tsx   (root-layout failures; owns <html>/<body>)
 *
 * A chart throwing at render must surface recovery UI (role=alert) with a
 * retry affordance wired to `reset()`, instead of a blank page.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RouteError from "@/app/error";
import AppGroupError from "@/app/(app)/error";
import GlobalError from "@/app/global-error";

afterEach(() => {
  cleanup();
});

describe("root segment boundary (app/error.tsx)", () => {
  it("renders recovery UI with role=alert for a render-time error", () => {
    const reset = vi.fn();
    render(<RouteError error={new Error("Chart exploded during render")} reset={reset} />);

    const alert = screen.getByRole("alert");
    expect(alert).not.toBeNull();
    expect(alert.textContent).toContain("Chart exploded during render");
  });

  it("retry affordance invokes reset()", async () => {
    const reset = vi.fn();
    render(<RouteError error={new Error("boom")} reset={reset} />);

    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(reset).toHaveBeenCalledTimes(1);
  });
});

describe("dashboard group boundary (app/(app)/error.tsx)", () => {
  it("renders recovery UI and wires reset()", async () => {
    const reset = vi.fn();
    render(<AppGroupError error={new Error("ScoreChart crashed")} reset={reset} />);

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("ScoreChart crashed");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(reset).toHaveBeenCalledTimes(1);
  });
});

describe("global boundary (app/global-error.tsx)", () => {
  it("owns an html/body shell and still offers recovery + reset", async () => {
    const reset = vi.fn();
    render(<GlobalError error={new Error("Root layout failed")} reset={reset} />);

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Root layout failed");

    // global-error.tsx must render its own document shell: our <body> (marked
    // with a testid) wraps the recovery UI, nested under an <html> element.
    // NOTE: happy-dom adopts the created <body> as document.body, so we walk
    // up from the alert instead of querying scoped containers.
    const shellBody = alert.closest("body");
    expect(shellBody?.getAttribute("data-testid")).toBe("global-error-body");
    expect(shellBody?.parentElement?.tagName).toBe("HTML");

    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(reset).toHaveBeenCalledTimes(1);
  });
});

describe("triangulation — distinct errors surface distinct messages", () => {
  it("shows the specific message, not a generic placeholder", () => {
    const reset = vi.fn();
    render(<RouteError error={new Error("FundingBar render failure #42")} reset={reset} />);
    expect(screen.getByRole("alert").textContent).toContain("FundingBar render failure #42");
  });

  it("does not invoke reset on mount (user-driven only)", () => {
    const reset = vi.fn();
    render(<RouteError error={new Error("idle")} reset={reset} />);
    expect(reset).not.toHaveBeenCalled();
  });
});
