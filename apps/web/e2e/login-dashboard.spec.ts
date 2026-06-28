import { expect, test } from "@playwright/test";

/**
 * PR B-2 (dashboard-redesign): the dashboard is now 3 zones
 * (Triage / Pipeline / Health). The legacy 4 KPI labels are demoted
 * into a <details> summary ("Ver resumen numérico") inside the Triage
 * zone. To assert the legacy strings "Convocatorias abiertas" and
 * "Alta compatibilidad" the test must first open the details element.
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

  // The legacy KPI labels now live inside a <details> summary in the
  // Triage zone. Open it before asserting.
  await page.locator('summary:has-text("Ver resumen numérico")').click();
  await expect(page.getByText(/Convocatorias abiertas/i)).toBeVisible();
  await expect(page.getByText(/Alta compatibilidad/i)).toBeVisible();

  await page.getByRole("link", { name: "Convocatorias", exact: true }).click();
  await expect(page).toHaveURL(/\/opportunities$/);
  await expect(page.getByRole("heading", { name: /Oportunidades activas/i })).toBeVisible();
  await expect(page.getByText(/Not Found/i)).toHaveCount(0);
});
