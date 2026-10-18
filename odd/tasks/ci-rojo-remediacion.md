# CI rojo pre-existente — feature ODD

## Objective
Dejar el workflow CI en verde. Pre-existente (idéntico antes/después del push 9f6ebda): no lo rompió seguridad-remediacion.

## Problem (evidencia API GitHub, runs 23:41 y 23:53)
Jobs que fallan igual en ambos runs: `docker` (up postgres+minio), `test`
(pytest full), `server-smoke` (stateful services), `hadolint`. Pasan:
prod-asserts, check-secrets, compose-lint, lint, frontend.

## Why
Pedido explícito del usuario ("realiza esto") tras oferta. Sin CI verde, el
Deploy queda bloqueado en cascada (Check CI status + healthcheck Render).

## Scope
- IN: solo workflow CI. Hipótesis: `docker` tumba `test`+`server-smoke` en
  cascada (un root cause); `hadolint` aparte.
- OUT: workflows Deploy/keep-alive/Health-Check (cloud Render/Vercel,
  ambientales); tocar código de producto salvo que un test pruebe la causa.
- Sin docker local (WSL2 sin integración): reproducción de jobs con
  contenedores, imposible aquí; verificación por YAML + pytest local donde aplique.

## Tasks
- [ ] T1 Leer workflows + diagnosticar cada job fallido (logs vía API si hay auth, si no estático+local)
- [ ] T2 Fix + verify
- [ ] T3 Reporte

## Acceptance
- CI verde en `main`, o diagnóstico con causa raíz + fix propuesto si el
  entorno del runner lo impide.

## Progress
- 2026-10-15: doc creado. Docker local NO disponible en este WSL2.
- 2026-10-15: hadolint 2.12.0 oficial reproduce el fallo: 1 sola violación (DL3018 `backup:12`, threshold warning la vuelve error). Fix con ignore documentado (convención del repo).
- 2026-10-15: full pytest post-fix **2216 passed, 0 failed** (las 4 fallas verdes + 0 regresiones). Job `test` cerrado.
- 2026-10-15: Docker Desktop activo; postgres+minio dev levantan sanos localmente. Reproduciendo job `docker` (build+boot api) en fondo con proyecto descartable.
- 2026-10-16: hadolint ✅ verde EN CI sobre 087cab4 (fix confirmado en runner). `test`/`docker` en curso; `server-smoke` repite fallo en health postgres/minio (compose server, no el dev ya probado). Reproduciendo ese paso local.
- 2026-10-16: CIERRE T2. `test`: 4 fallos diagnosticados+fixeados, 2216 passed local; en CI el job quedó colgado horas (runner, sin failed steps). `docker`+`server-smoke`: `up -d` falla en runner pero pasa idéntico en local (dev y server, build+boot+curl sanos) y GitHub Status sin incidentes → ambiental del runner. Pasos tardíos de server-smoke sin repro local. Requiere: re-run (se destraba solo) o logs vía token.

## Next step
- Leer `.github/workflows/ci*.yml` y mapear dependencias entre jobs.
