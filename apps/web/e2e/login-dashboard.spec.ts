import { expect, test } from "@playwright/test";

/**
 * PR B-2 (dashboard-redesign): the dashboard is now 3 zones
 * (Triage / Pipeline / Health). The legacy 4 KPI labels live in the
 * HealthZone as the 4 stat cards (they no longer sit in a collapsible
 * inside the Triage zone). We assert them directly without opening
 * any <details> because the HealthZone renders them as soon as the
 * data resolves.
 */
test("inicia sesion y carga el panel analitico", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/login", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: /ConvocaRadar IA/i })).toBeVisible();

  // SEC-1.3: in production builds (NEXT_PUBLIC_ENV=production, the default
  // in CI's `npm run build && npm run start`) the dev-credentials button
  // is hidden. Fill the email + password form directly. The seed CLI
  // creates an admin@convocaradar.io / ConvocaRadarLocal123! local user.
  const email = process.env.E2E_TEST_EMAIL ?? "admin@convocaradar.io";
  const password = process.env.E2E_TEST_PASSWORD ?? "ConvocaRadarLocal123!";
  await page.getByLabel(/correo|email/i).fill(email);
  await page.getByLabel(/contraseña|password/i).fill(password);
  await page.getByRole("button", { name: /^Ingresar$/i }).click();

  await expect(page).toHaveURL(/\/dashboard$/);

  // PR B-2: 3 zones each render their own heading.
  await expect(page.getByText(/qu[ée]\s+hago\s+hoy/i)).toBeVisible();
  await expect(page.getByText(/top compatibilidad/i)).toBeVisible();
  await expect(page.getByText(/estado de convocatorias/i)).toBeVisible();

  // The legacy KPI labels are surfaced in two zones: inside the
  // TriageZone's <details> collapsible (hidden until opened) and
  // inside the HealthZone's 4 stat cards (always visible). Scope the
  // assertion to the HealthZone so we assert the visible one.
  const healthZone = page.locator("[data-zone='health']");
  await expect(healthZone.getByText(/Convocatorias abiertas/i)).toBeVisible();
  await expect(healthZone.getByText(/Alta compatibilidad/i)).toBeVisible();

  await page.getByRole("link", { name: "Convocatorias", exact: true }).click();
  await expect(page).toHaveURL(/\/opportunities$/);
  await expect(page.getByRole("heading", { name: /Oportunidades activas/i })).toBeVisible();
  await expect(page.getByText(/Not Found/i)).toHaveCount(0);
});
