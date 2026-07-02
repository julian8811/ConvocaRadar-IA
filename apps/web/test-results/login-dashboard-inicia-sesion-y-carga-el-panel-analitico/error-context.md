# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: login-dashboard.spec.ts >> inicia sesion y carga el panel analitico
- Location: e2e/login-dashboard.spec.ts:11:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText(/estado de convocatorias/i)
Expected: visible
Timeout: 15000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 15000ms
  - waiting for getByText(/estado de convocatorias/i)

```

```yaml
- complementary:
  - img
  - paragraph: ConvocaRadar IA
  - paragraph: Inteligencia empresarial
  - link "Panel":
    - /url: /dashboard
    - img
    - text: Panel
  - link "Convocatorias":
    - /url: /opportunities
    - img
    - text: Convocatorias
  - link "Fuentes":
    - /url: /sources
    - img
    - text: Fuentes
  - link "Reportes":
    - /url: /reports
    - img
    - text: Reportes
  - link "Alertas":
    - /url: /alerts
    - img
    - text: Alertas
  - link "Perfil":
    - /url: /onboarding
    - img
    - text: Perfil
  - link "Administración":
    - /url: /admin
    - img
    - text: Administración
  - link "Configuración":
    - /url: /settings
    - img
    - text: Configuración
  - paragraph: Sesión activa
  - paragraph: Admin ConvocaRadar
  - paragraph: admin
  - button "Salir":
    - img
    - text: Salir
- main:
  - img
  - textbox "Búsqueda semántica de convocatorias..."
  - button "Cambiar a modo oscuro":
    - img
    - text: Modo oscuro
  - text: AC
  - heading "Próximos cierres (7 días)" [level=2]
  - paragraph: Convocatorias que cierran esta semana.
  - table:
    - rowgroup:
      - row "Convocatoria País Cierra en Monto":
        - columnheader "Convocatoria"
        - columnheader "País"
        - columnheader "Cierra en"
        - columnheader "Monto"
    - rowgroup:
      - row "Proyectos Macrorrueda Colombia -1489 días Por validar":
        - cell "Proyectos Macrorrueda":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
        - cell "Colombia"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda Colombia -1489 días Por validar":
        - cell "Proyectos Macrorrueda":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
        - cell "Colombia"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda Colombia -1489 días Por validar":
        - cell "Proyectos Macrorrueda":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
        - cell "Colombia"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda Colombia -1489 días Por validar":
        - cell "Proyectos Macrorrueda":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
        - cell "Colombia"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda Colombia -1489 días Por validar":
        - cell "Proyectos Macrorrueda":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
        - cell "Colombia"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda Colombia -1489 días Por validar":
        - cell "Proyectos Macrorrueda":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
        - cell "Colombia"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda Colombia -1489 días Por validar":
        - cell "Proyectos Macrorrueda":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
        - cell "Colombia"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda Colombia -1489 días Por validar":
        - cell "Proyectos Macrorrueda":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
        - cell "Colombia"
        - cell "-1489 días"
        - cell "Por validar"
  - heading "Qué hago hoy" [level=2]
  - paragraph: Acciones prioritarias basadas en tu radar.
  - text: "1"
  - img
  - paragraph: 8 convocatorias cierran esta semana
  - link "Ver":
    - /url: "#closing-soon-7d"
    - text: Ver
    - img
  - text: "2"
  - img
  - paragraph: 8 items en tu cola de revisión
  - link "Revisar":
    - /url: "#review-queue"
    - text: Revisar
    - img
  - text: "3"
  - img
  - paragraph: Refuerza tu perfil institucional para mejorar la compatibilidad
  - link "Completar":
    - /url: /onboarding
    - text: Completar
    - img
  - group: Ver resumen numérico
  - heading "Top compatibilidad" [level=3]:
    - img
    - text: Top compatibilidad
  - paragraph: Convocatorias con mejor score y las razones que lo explican.
  - table:
    - rowgroup:
      - row "Convocatoria País Score Razones Monto":
        - columnheader "Convocatoria"
        - columnheader "País"
        - columnheader "Score"
        - columnheader "Razones"
        - columnheader "Monto"
    - rowgroup:
      - row "SERVICIOS COMPLEMENTARIOS LOGÍSTICOS, DE COLABORACIÓN Y CÓDIGOS DE BARRAS Colombia 75 La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más Por validar":
        - cell "SERVICIOS COMPLEMENTARIOS LOGÍSTICOS, DE COLABORACIÓN Y CÓDIGOS DE BARRAS":
          - link "SERVICIOS COMPLEMENTARIOS LOGÍSTICOS, DE COLABORACIÓN Y CÓDIGOS DE BARRAS":
            - /url: /opportunities/ba78093c-0dc4-4ff7-bbb8-3a57469a9e1a
        - cell "Colombia"
        - cell "75":
          - paragraph: "75"
        - cell "La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más":
          - list:
            - listitem: La región de la convocatoria es compatible con el perfil.
            - listitem: El tipo de organización parece elegible.
            - listitem: +3 más
        - cell "Por validar"
      - row "ZASCA Tecnologías Putumayo | C2.1 | Postulación presencial Colombia 75 La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más Por validar":
        - cell "ZASCA Tecnologías Putumayo | C2.1 | Postulación presencial":
          - link "ZASCA Tecnologías Putumayo | C2.1 | Postulación presencial":
            - /url: /opportunities/a1b648c7-9cdc-4b46-bed8-fa60a9638387
        - cell "Colombia"
        - cell "75":
          - paragraph: "75"
        - cell "La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más":
          - list:
            - listitem: La región de la convocatoria es compatible con el perfil.
            - listitem: El tipo de organización parece elegible.
            - listitem: +3 más
        - cell "Por validar"
      - row "ZASCA Tecnologías | Norte de Santander | Postulación presencial | Cohorte 2 Colombia 75 La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más Por validar":
        - cell "ZASCA Tecnologías | Norte de Santander | Postulación presencial | Cohorte 2":
          - link "ZASCA Tecnologías | Norte de Santander | Postulación presencial | Cohorte 2":
            - /url: /opportunities/7bf5cd84-a6af-4e1c-a449-c74d5d436d0f
        - cell "Colombia"
        - cell "75":
          - paragraph: "75"
        - cell "La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más":
          - list:
            - listitem: La región de la convocatoria es compatible con el perfil.
            - listitem: El tipo de organización parece elegible.
            - listitem: +3 más
        - cell "Por validar"
      - row "ZASCA Tecnologías Honda Norte del Tolima y Guaduas. (Postulación Presencial) Colombia 75 La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más Por validar":
        - cell "ZASCA Tecnologías Honda Norte del Tolima y Guaduas. (Postulación Presencial)":
          - link "ZASCA Tecnologías Honda Norte del Tolima y Guaduas. (Postulación Presencial)":
            - /url: /opportunities/9b3c9c85-317b-4e63-8bf6-c3d7b2b215ac
        - cell "Colombia"
        - cell "75":
          - paragraph: "75"
        - cell "La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más":
          - list:
            - listitem: La región de la convocatoria es compatible con el perfil.
            - listitem: El tipo de organización parece elegible.
            - listitem: +3 más
        - cell "Por validar"
      - row "ZASCA Tecnologías | Caquetá | Cohorte 2 (Postulación Presencial) Colombia 75 La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más Por validar":
        - cell "ZASCA Tecnologías | Caquetá | Cohorte 2 (Postulación Presencial)":
          - link "ZASCA Tecnologías | Caquetá | Cohorte 2 (Postulación Presencial)":
            - /url: /opportunities/8d9ccccf-3145-4057-a5ed-7a870aeae413
        - cell "Colombia"
        - cell "75":
          - paragraph: "75"
        - cell "La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más":
          - list:
            - listitem: La región de la convocatoria es compatible con el perfil.
            - listitem: El tipo de organización parece elegible.
            - listitem: +3 más
        - cell "Por validar"
      - 'row "Convocatoria: ZASCA Tecnologías | Casanare | Cohorte 2 (Postulación Presencial) Colombia 75 La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más Por validar"':
        - 'cell "Convocatoria: ZASCA Tecnologías | Casanare | Cohorte 2 (Postulación Presencial)"':
          - 'link "Convocatoria: ZASCA Tecnologías | Casanare | Cohorte 2 (Postulación Presencial)"':
            - /url: /opportunities/730627cd-2b76-424a-b017-e363bbc7003f
        - cell "Colombia"
        - cell "75":
          - paragraph: "75"
        - cell "La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más":
          - list:
            - listitem: La región de la convocatoria es compatible con el perfil.
            - listitem: El tipo de organización parece elegible.
            - listitem: +3 más
        - cell "Por validar"
      - row "ZASCA Manufactura Ibagué | Cohorte 4.1 Colombia 75 La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más Por validar":
        - cell "ZASCA Manufactura Ibagué | Cohorte 4.1":
          - link "ZASCA Manufactura Ibagué | Cohorte 4.1":
            - /url: /opportunities/ed4c17b2-e25c-4571-8035-8c84a41356a7
        - cell "Colombia"
        - cell "75":
          - paragraph: "75"
        - cell "La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más":
          - list:
            - listitem: La región de la convocatoria es compatible con el perfil.
            - listitem: El tipo de organización parece elegible.
            - listitem: +3 más
        - cell "Por validar"
      - row "SOSTENIBILIDAD PARA LA CADENA DE VALOR DEL TURISMO Colombia 75 La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más Por validar":
        - cell "SOSTENIBILIDAD PARA LA CADENA DE VALOR DEL TURISMO":
          - link "SOSTENIBILIDAD PARA LA CADENA DE VALOR DEL TURISMO":
            - /url: /opportunities/82def29d-454c-4222-8901-ba05afc9940f
        - cell "Colombia"
        - cell "75":
          - paragraph: "75"
        - cell "La región de la convocatoria es compatible con el perfil. El tipo de organización parece elegible. +3 más":
          - list:
            - listitem: La región de la convocatoria es compatible con el perfil.
            - listitem: El tipo de organización parece elegible.
            - listitem: +3 más
        - cell "Por validar"
  - heading "Cierran pronto" [level=3]:
    - img
    - text: Cierran pronto
  - paragraph: Convocatorias con fecha de cierre cercana.
  - table:
    - rowgroup:
      - row "Convocatoria País Score Cierra en Monto":
        - columnheader "Convocatoria"
        - columnheader "País"
        - columnheader "Score"
        - columnheader "Cierra en"
        - columnheader "Monto"
    - rowgroup:
      - row "Event Support for 2027 Multilateral Action on Sensitive Technologies (MAST) Plenary United States 50 Hoy Por validar":
        - cell "Event Support for 2027 Multilateral Action on Sensitive Technologies (MAST) Plenary":
          - link "Event Support for 2027 Multilateral Action on Sensitive Technologies (MAST) Plenary":
            - /url: /opportunities/2b74f9f7-748f-48c7-8c60-9b2f011bb742
        - cell "United States"
        - cell "50":
          - paragraph: "50"
        - cell "Hoy"
        - cell "Por validar"
      - row "Event Support for 2027 Multilateral Action on Sensitive Technologies (MAST) Plenary United States 50 Hoy Por validar":
        - cell "Event Support for 2027 Multilateral Action on Sensitive Technologies (MAST) Plenary":
          - link "Event Support for 2027 Multilateral Action on Sensitive Technologies (MAST) Plenary":
            - /url: /opportunities/607dd3a9-85ce-460b-b148-33863948db3c
        - cell "United States"
        - cell "50":
          - paragraph: "50"
        - cell "Hoy"
        - cell "Por validar"
      - row "Event Support for 2027 Multilateral Action on Sensitive Technologies (MAST) Plenary United States 50 Hoy Por validar":
        - cell "Event Support for 2027 Multilateral Action on Sensitive Technologies (MAST) Plenary":
          - link "Event Support for 2027 Multilateral Action on Sensitive Technologies (MAST) Plenary":
            - /url: /opportunities/1d546237-4798-40a5-9a88-7665a984004d
        - cell "United States"
        - cell "50":
          - paragraph: "50"
        - cell "Hoy"
        - cell "Por validar"
      - row "Building English Teaching Capacity for STEM in Brazil United States 50 Hoy Por validar":
        - cell "Building English Teaching Capacity for STEM in Brazil":
          - link "Building English Teaching Capacity for STEM in Brazil":
            - /url: /opportunities/9be28367-9bba-45b5-8de3-10df5921423b
        - cell "United States"
        - cell "50":
          - paragraph: "50"
        - cell "Hoy"
        - cell "Por validar"
      - row "Test GUARDIANS před investováním Open Call European Union 40 Hoy Por validar":
        - cell "Test GUARDIANS před investováním Open Call":
          - link "Test GUARDIANS před investováním Open Call":
            - /url: /opportunities/335b6344-54aa-4aa0-810e-3678203c8430
        - cell "European Union"
        - cell "40":
          - paragraph: "40"
        - cell "Hoy"
        - cell "Por validar"
      - row "FY26 EducationUSA Nigeria Advising United States 50 1 día Por validar":
        - cell "FY26 EducationUSA Nigeria Advising":
          - link "FY26 EducationUSA Nigeria Advising":
            - /url: /opportunities/210e0a3f-4468-4591-b5cf-604450954fa8
        - cell "United States"
        - cell "50":
          - paragraph: "50"
        - cell "1 día"
        - cell "Por validar"
      - row "ZASCA Agroindustria | Guaviare | Productos Forestales No Maderables | Cohorte 2 ASOPROAGRO Colombia 75 3 días Por validar":
        - cell "ZASCA Agroindustria | Guaviare | Productos Forestales No Maderables | Cohorte 2 ASOPROAGRO":
          - link "ZASCA Agroindustria | Guaviare | Productos Forestales No Maderables | Cohorte 2 ASOPROAGRO":
            - /url: /opportunities/e4acc9f8-90a7-4c3a-a1bf-f82bebae2b38
        - cell "Colombia"
        - cell "75":
          - paragraph: "75"
        - cell "3 días"
        - cell "Por validar"
      - row "ZASCA Agroindustria | Guaviare | Productos Forestales No Maderables | Cohorte 2 COMGUAVIARE Colombia 75 3 días Por validar":
        - cell "ZASCA Agroindustria | Guaviare | Productos Forestales No Maderables | Cohorte 2 COMGUAVIARE":
          - link "ZASCA Agroindustria | Guaviare | Productos Forestales No Maderables | Cohorte 2 COMGUAVIARE":
            - /url: /opportunities/c3395ad7-8a50-4119-a555-e95f671f8cbd
        - cell "Colombia"
        - cell "75":
          - paragraph: "75"
        - cell "3 días"
        - cell "Por validar"
  - heading "Mi cola de revisión" [level=3]:
    - img
    - text: Mi cola de revisión
  - paragraph: Items que marcaste como En revisión o Mantener.
  - table:
    - rowgroup:
      - row "Convocatoria País Score Cierra en Monto":
        - columnheader "Convocatoria"
        - columnheader "País"
        - columnheader "Score"
        - columnheader "Cierra en"
        - columnheader "Monto"
    - rowgroup:
      - row "Proyectos Macrorrueda En revisión Colombia 45 -1489 días Por validar":
        - cell "Proyectos Macrorrueda En revisión":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
          - paragraph: En revisión
        - cell "Colombia"
        - cell "45":
          - paragraph: "45"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda En revisión Colombia 45 -1489 días Por validar":
        - cell "Proyectos Macrorrueda En revisión":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
          - paragraph: En revisión
        - cell "Colombia"
        - cell "45":
          - paragraph: "45"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda En revisión Colombia 45 -1489 días Por validar":
        - cell "Proyectos Macrorrueda En revisión":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
          - paragraph: En revisión
        - cell "Colombia"
        - cell "45":
          - paragraph: "45"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda En revisión Colombia 45 -1489 días Por validar":
        - cell "Proyectos Macrorrueda En revisión":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
          - paragraph: En revisión
        - cell "Colombia"
        - cell "45":
          - paragraph: "45"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda En revisión Colombia 45 -1489 días Por validar":
        - cell "Proyectos Macrorrueda En revisión":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
          - paragraph: En revisión
        - cell "Colombia"
        - cell "45":
          - paragraph: "45"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda En revisión Colombia 45 -1489 días Por validar":
        - cell "Proyectos Macrorrueda En revisión":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
          - paragraph: En revisión
        - cell "Colombia"
        - cell "45":
          - paragraph: "45"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda En revisión Colombia 45 -1489 días Por validar":
        - cell "Proyectos Macrorrueda En revisión":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
          - paragraph: En revisión
        - cell "Colombia"
        - cell "45":
          - paragraph: "45"
        - cell "-1489 días"
        - cell "Por validar"
      - row "Proyectos Macrorrueda En revisión Colombia 45 -1489 días Por validar":
        - cell "Proyectos Macrorrueda En revisión":
          - link "Proyectos Macrorrueda":
            - /url: /opportunities/d67bde2d-be3d-4096-baea-56f56845d3e3
          - paragraph: En revisión
        - cell "Colombia"
        - cell "45":
          - paragraph: "45"
        - cell "-1489 días"
        - cell "Por validar"
- region "Notifications alt+T"
- alert
```

# Test source

```ts
  1  | import { expect, test } from "@playwright/test";
  2  | 
  3  | /**
  4  |  * PR B-2 (dashboard-redesign): the dashboard is now 3 zones
  5  |  * (Triage / Pipeline / Health). The legacy 4 KPI labels live in the
  6  |  * HealthZone as the 4 stat cards (they no longer sit in a collapsible
  7  |  * inside the Triage zone). We assert them directly without opening
  8  |  * any <details> because the HealthZone renders them as soon as the
  9  |  * data resolves.
  10 |  */
  11 | test("inicia sesion y carga el panel analitico", async ({ page }) => {
  12 |   test.setTimeout(120_000);
  13 |   await page.goto("/login", { waitUntil: "domcontentloaded" });
  14 | 
  15 |   await expect(page.getByRole("heading", { name: /ConvocaRadar IA/i })).toBeVisible();
  16 | 
  17 |   // SEC-1.3: in production builds (NEXT_PUBLIC_ENV=production, the default
  18 |   // in CI's `npm run build && npm run start`) the dev-credentials button
  19 |   // is hidden. Fill the email + password form directly. The seed CLI
  20 |   // creates an admin@convocaradar.io / ConvocaRadarLocal123! local user.
  21 |   const email = process.env.E2E_TEST_EMAIL ?? "admin@convocaradar.io";
  22 |   const password = process.env.E2E_TEST_PASSWORD ?? "ConvocaRadarLocal123!";
  23 |   await page.getByLabel(/correo|email/i).fill(email);
  24 |   await page.getByLabel(/contraseña|password/i).fill(password);
  25 |   await page.getByRole("button", { name: /^Ingresar$/i }).click();
  26 | 
  27 |   await expect(page).toHaveURL(/\/dashboard$/);
  28 | 
  29 |   // PR B-2: 3 zones each render their own heading.
  30 |   await expect(page.getByText(/qu[ée]\s+hago\s+hoy/i)).toBeVisible();
  31 |   await expect(page.getByText(/top compatibilidad/i)).toBeVisible();
> 32 |   await expect(page.getByText(/estado de convocatorias/i)).toBeVisible();
     |                                                            ^ Error: expect(locator).toBeVisible() failed
  33 | 
  34 |   // The legacy KPI labels are surfaced in two zones: inside the
  35 |   // TriageZone's <details> collapsible (hidden until opened) and
  36 |   // inside the HealthZone's 4 stat cards (always visible). Scope the
  37 |   // assertion to the HealthZone so we assert the visible one.
  38 |   const healthZone = page.locator("[data-zone='health']");
  39 |   await expect(healthZone.getByText(/Convocatorias abiertas/i)).toBeVisible();
  40 |   await expect(healthZone.getByText(/Alta compatibilidad/i)).toBeVisible();
  41 | 
  42 |   await page.getByRole("link", { name: "Convocatorias", exact: true }).click();
  43 |   await expect(page).toHaveURL(/\/opportunities$/);
  44 |   await expect(page.getByRole("heading", { name: /Oportunidades activas/i })).toBeVisible();
  45 |   await expect(page.getByText(/Not Found/i)).toHaveCount(0);
  46 | });
  47 | 
```