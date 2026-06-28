import { expect, test } from "@playwright/test";

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
  await expect(page.getByRole("heading", { name: /Panel anal[ií]tico/i })).toBeVisible();
  await expect(page.getByText(/Convocatorias abiertas/i)).toBeVisible();
  await expect(page.getByText(/Alta compatibilidad/i)).toBeVisible();

  await page.getByRole("link", { name: "Convocatorias", exact: true }).click();
  await expect(page).toHaveURL(/\/opportunities$/);
  await expect(page.getByRole("heading", { name: /Oportunidades activas/i })).toBeVisible();
  await expect(page.getByText(/Not Found/i)).toHaveCount(0);
});
