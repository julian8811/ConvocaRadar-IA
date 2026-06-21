import { expect, test } from "@playwright/test";

test("inicia sesi�n y carga el panel anal�tico", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/login", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: /ConvocaRadar IA/i })).toBeVisible();
  await page.getByRole("button", { name: /Entrar con cuenta local/i }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: /Panel anal�tico/i })).toBeVisible();
  await expect(page.getByText(/Convocatorias abiertas/i)).toBeVisible();
  await expect(page.getByText(/Cobertura de embeddings/i)).toBeVisible();

  await page.getByRole("link", { name: /Convocatorias/i }).click();
  await expect(page).toHaveURL(/\/opportunities$/);
  await expect(page.getByRole("heading", { name: /Oportunidades activas/i })).toBeVisible();
  await expect(page.getByText(/Not Found/i)).toHaveCount(0);
});
