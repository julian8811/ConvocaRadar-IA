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
- [ ] **T1 (P0 web)** Timeout largo para runAll (120s, patrón como login 65s) + toast amigable ante abort ("el barrido sigue en segundo plano") en vez del mensaje DOM crudo. Tests vitest (RED: runAll usa default 12s). Ruta: delegada (writer único T1-T3).
- [ ] **T2 (P0 api)** `POST /sources/run-all` responde 202/`started` inmediato: mover el trabajo síncrono pesado (carga de catálogo) al thread de fondo, creando solo la fila Task + commit mínimo antes de responder. Sin cambiar semántica de auditoría ni filtros. Tests pytest (RED: el POST hace load síncrono antes de responder). Ruta: delegada.
- [ ] **T3 (P0 scraper)** Migrar `HTMLParser` (Modest) → `LexborHTMLParser` en conectores + `dom_monitor.py`; verificar compat API (css/text/attributes) con tests de conectores en verde; pin o doc si lexbor diverge en algún selector. Tests pytest (RED: scrape de fixture falla con error Modest). Ruta: delegada.
- [ ] **T4 (P1 deploy, PENDIENTE autorización)** Port a `server/observatorio-production-prebasepath-20260909` (cherry-pick), rebuild api/worker, clic "Ejecutar todas" cronometrado + logs `run_all.completed` con ítems > 0. No iniciar sin autorización explícita del usuario.

## Acceptance
- Clic "Ejecutar todas" en el server → sin toast de abort; `task_id` en estado `running` → `completed`.
- Logs worker sin errores selectolax; `items_found > 0` en una muestra de fuentes.
- Suites verde: `pytest tests/` (api) + `npm run test` (web).

## Progress
- 2026-10-09: doc creado en `feature/convocaradar-runall-abort`. Exploración delegada (mapa completo + 3 hipótesis) + logs de prod como evidencia. Supuesto resuelto por usuario: prueba solo en server universitario.

## Verification evidence
- (comando → resultado observado, por tarea)

## Next step
- Lanzar writer único T1-T3 con TDD RED→GREEN→REFACT0R.
