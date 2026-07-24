import { expect, test } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel(/correo|email/i).fill(
    process.env.E2E_TEST_EMAIL ?? "admin@convocaradar.io",
  );
  await page.getByLabel(/contraseña|password/i).fill(
    process.env.E2E_TEST_PASSWORD ?? "ConvocaRadarLocal123!",
  );
  await page.getByRole("button", { name: /^Ingresar$/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test("todas las secciones principales cargan sin errores del servidor", async ({ page }) => {
  const serverErrors: string[] = [];
  page.on("response", (response) => {
    if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`);
  });

  await login(page);
  for (const route of [
    "/dashboard",
    "/opportunities",
    "/sources",
    "/alerts",
    "/reports",
    "/settings",
    "/admin",
  ]) {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(new RegExp(`${route}$`));
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByText(/Not Found|Internal Server Error/i)).toHaveCount(0);
  }

  expect(serverErrors).toEqual([]);
});

test("el tema persiste y cerrar sesión protege las páginas privadas", async ({ page }) => {
  await login(page);
  const themeButton = page.getByRole("button", { name: /Cambiar a modo/i });
  await expect(themeButton).toBeVisible();
  await themeButton.click();
  const storedTheme = await page.evaluate(() => localStorage.getItem("observatorio-theme"));
  expect(storedTheme).toMatch(/light|dark/);

  await page.reload();
  await expect(page.getByRole("button", { name: /Cambiar a modo/i })).toBeVisible();
  await page.getByRole("button", { name: /^Salir$/i }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
});
