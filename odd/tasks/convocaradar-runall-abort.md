# RunAll abort + selectolax muerto — feature ODD

## Objective
Que "Ejecutar todas" funcione de punta a punta: sin abort del frontend a los 12s y con scrapers que extraigan datos reales (0 fallos por parser).

## Problem
1. `apps/web/lib/api.ts:123-128` aborta todo request a los 12s (`controller.abort()` sin reason → DOM `AbortError: "signal is aborted without reason"`), y `runAllSources` (`api.ts:300`) usa ese default. El `POST /sources/run-all` hace trabajo síncrono pesado (carga 201 fuentes + Task + commits, `sources.py:429-501,629-631`) que en el server supera 12s → toast de error aunque el sweep sí arrancó. Verificado en código (spot-check padre).
2. El backend scraper está muerto: `from selectolax.parser import HTMLParser` (backend Modest, removido/deprecado en selectolax 1.x) hace fallar el 100% de los scrapes (`scraper_source_error`, 0 ítems, worker logs 2026-10-09). ~25 call sites en `apps/api/app/connectors/*.py` + `dom_monitor.py` + 1 test + 1 script. Ruta oficial: `selectolax.lexbor.LexborHTMLParser`.
3. Ningún `run_all` llegó al api universitario en la vida del container actual → el usuario prueba solo ahí (confirmado por él), así que el fix va a `main` y luego se portea a la rama server (patrón ya usado: cherry-pick + rebuild).

## Why
Sin esto el botón principal del observatorio es un error garantizado y el harvest real está en cero: los fixes b6f1564/2fd7ce6 quedaron verificados pero el sistema sigue sin extraer nada.

## Scope
- IN: `apps/web/lib/api.ts`, `apps/web/app/(app)/sources/page.tsx`, tests web; `apps/api/app/api/v1/sources.py` + `tests/test_sources.py`; migración lexbor en `apps/api/app/connectors/*.py`, `app/scraper/dom_monitor.py`, test afectado.
- OUT: rama server + rebuild + clic e2e (T4, requiere autorización del usuario en su momento); Render/Vercel (deploy automático por CI, sin acción); CEITTO.

## Constraints
- Conventional Commits, sin atribución IA. Rama feature desde `main` (limpio en `b6f1564`). Push/PR/merge los decide el usuario.
- TDD ON (convención del repo). API: `cd apps/api && pytest tests/` (focado por tarea, completa al cierre). Web: `npm run test` (vitest) + typecheck si existe.
- RDD ON (global): writer corre `## Verification` en foreground y reporta `comando: resultado`; review nativa como chequeo independiente por work-unit commit.
- Delivery `ask-on-risk`, heurística ~400 líneas (la migración lexbor es mecánica: 1 línea por archivo × ~25 + verificación).

## Tasks
- [x] **T1 (P0 web)** ✅ commit `aa7d0c9` (writer delegado, TDD RED→GREEN: 3 failed → 20 passed). `RUN_ALL_TIMEOUT_MS=120s` + `isAbortError`/`RUN_ALL_ABORT_MESSAGE` en `api.ts`; toast amigable en `page.tsx`. Ruta: delegada.
- [x] **T2 (P0 api)** ✅ commit `31bba40` (writer delegado, TDD RED→GREEN: 11 passed). POST responde 202 con Task mínima; catálogo + decisiones en el thread. Tests actualizados 200→202. Ruta: delegada.
- [x] **T3 (P0 scraper)** ✅ commit `9e0aecb` (writer delegado, TDD RED→GREEN: guard 2 failed → 13 passed; triangulación 573 passed). 23 conectores + `dom_monitor.py` a lexbor; mecanismo confirmado: prod tiene selectolax 1.0.0 (Modest levanta ImportError), local 0.4.10. Ruta: delegada.
- [ ] **T4 (P1 deploy, PENDIENTE autorización)** Port a `server/observatorio-production-prebasepath-20260909` (cherry-pick), rebuild api/worker, clic "Ejecutar todas" cronometrado + logs `run_all.completed` con ítems > 0. No iniciar sin autorización explícita del usuario.

## Acceptance
- Clic "Ejecutar todas" en el server → sin toast de abort; `task_id` en estado `running` → `completed`.
- Logs worker sin errores selectolax; `items_found > 0` en una muestra de fuentes.
- Suites verde: `pytest tests/` (api) + `npm run test` (web).

## Progress
- 2026-10-09: doc creado en `feature/convocaradar-runall-abort`. Exploración delegada (mapa completo + 3 hipótesis) + logs de prod como evidencia. Supuesto resuelto por usuario: prueba solo en server universitario.
- 2026-10-09: T1-T3 implementados y commiteados (`aa7d0c9`, `31bba40`, `9e0aecb`). Review nativa: T1 `medium/under_budget` (sigue en slice); slice T1-T3 `medium/slice_budget_reached` → review aprobado con 3 WARNING advisory (R3-scope-unbound, R3-abort-recognition, R3-lexbor-node-parity; lineage `review-b13e57733fa66200`, authority burned). Engram mirror pendiente (conflicto de sesiones múltiples).

## Verification evidence
- `pytest tests/test_sources.py -q` → 11 passed (writer) + spot-check padre 11 passed.
- `pytest -k "connector or html or scraper or parse or lexbor or closed or dom"` → 573 passed.
- `npm run test -- --run __tests__/api.test.ts` → 20 passed.
- `ruff check` archivos tocados → exit 0.
- Prod: selectolax 1.0.0 + `selectolax.lexbor` OK (verificado por padre vía docker exec); `requirements.txt` deja `selectolax` sin pin (1.0.0 trae lexbor, no se cambia nada).

## Follow-ups (no bloqueantes, fuera de este slice)
- `apps/api/scripts/re_scrape_detail.py:106` sigue en Modest (fuera de superficie autorizada).
- R3-scope-unbound: si la carga del catálogo falla antes de asignar scope, `_record_sweep_scope` referencia locales sin asignar.
- R3-abort-recognition: `isAbortError` solo cubre `Error` con nombre AbortError.
- R3-lexbor-node-parity: paridad probada a nivel parser, no a nivel `Node` específico.

## Next step
- T4 deploy al server (requiere autorización): port a rama server, rebuild, clic e2e.
