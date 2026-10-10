# Cirugía mayor (10 duras) — feature ODD

## Objective
Resolver las 10 fuentes duras con cirugía mayor: cliente F&T API v2 unificado, render opt-in en producción y descubrimiento JS; lo bloqueado por WAF va a cuarentena con motivo + sign-off.

## Problem
Mapa verificado (explorer read-only + evidencia previa): Chromium YA viaja en imágenes api/worker (Dockerfile build-time, slot=1); patrón F&T v2 funcional existe (`eic_accelerator`, apiKey pública `SEDIA` sin cuenta); gate `browser_fallback<1500` inaplicable a SSR pesadas; WAF bilaterales sin DOM (sloan, ccb).

## Why
Decisión explícita del usuario: cirugía mayor (opción a).

## Scope
- IN: F0 probes padre; F1 conector F&T v2 parametrizado (erc/horizon/msca/creative); F2 flag render opt-in (danida + fallback); F3 descubrimiento JS + split startup (3 subfuentes, con aprobación); F4 cuarentenas + T4/T5/T6 heredados.
- OUT: tocar las 172 sanas, pipeline dedupe/ruido, umbrales/timeouts globales, EIC/Fapemig verdes.
- Decisiones del usuario pendientes: split startup 3×, sign-off WAF (ccb/sloan), cuenta F&T vs `SEDIA` público (default: seguir con `SEDIA`).

## Constraints
- Mismo circuito: writer local + tests TDD + PR + port + rebuild + reseed + verify por fuente. Servidor: agregados y runs acotados, secretos nunca fuera.
- Snapshots DOM server-side vía Chromium DEL CONTENEDOR api (ya instalado), no Playwright en host.
- Push/merge: el usuario (delegado "todo" en este flujo).

## Tasks
- [x] **F0 (P0 padre)** ✅ Probes 2026-10-10: F&T v2 con `apiKey=SEDIA` → 200 + metadata (ERC/MSCA/CREA), sin cuenta necesaria. Render Chromium en api OK: sloan = challenge Cloudflare (28KB, sin fix), ccb = Access Denied 337B (sin fix), findeter = página completa 387KB con título (contenido accesible, falla el parse → F1/F2). Script vía stdin (`docker exec -i`, rootfs read-only impide `docker cp`).
- [x] **F1 (P0 writer)** ✅ 2026-10-10 Conector F&T v2 parametrizado (erc/horizon/msca/creative) con filtros por programa + tests fixtures del probe; conectores viejos pruneados. Commits `cd72be2` (feat: conector unificado + migración) + `af3e181` (refactor: prune v1). Rama `feature/fuentes-f1-ftv2`, sin push (portea el padre con rebuild+reseed y verifica por fuente).
- [ ] **F2 (P1 writer)** Flag render opt-in (`force_render`/`wait_selector`) en `ConfigurableHtml` o dedicado (danida primero); evaluar slot 1→2.
- [ ] **F3 (P1)** Descubrimiento JS (finep Liferay, startup split con aprobación) + dictámenes.
- [ ] **F4 (P1)** Cuarentenas verificadas + T4 ruido + T5 timeouts + T6 sweep cierre.

## Acceptance
- 4 F&T en success con ítems; danida/finep/startup resueltas o con dictamen; WAF con motivo + sign-off; suite verde; nada sano tocado.

## Progress
- 2026-10-10: doc creado (5 tareas F0–F4). Mapa explorer completo. Mirror Engram pendiente.
- 2026-10-10: F0 completo (padre inline). sloan/ccb → cuarentena con motivo (WAF persiste con render); findeter Parisable.

## Verification evidence
- F1 (writer, rama `feature/fuentes-f1-ftv2`, commits `cd72be2`+`af3e181`, sin push):
  - RED: `ErcCallsConnector.parse` (v1) vs payload v2 real → 0 candidatos (shape muerta); `HorizonSediaConnector.parse` sin filtro vs payload MSCA real → 1 candidato (contaminación cruzada); suite nueva 21 failed pre-módulo (ModuleNotFoundError/KeyError/seeds html).
  - GREEN: `tests/test_ft_search_v2.py` 37 passed (programas disjuntos 1/1/1/1 sobre payload mixto, `_is_openish`, fetch POST+apiKey mockeado, seeds api); suites tocadas 94 passed; suite completa apps/api **1661 passed**; `ruff check` limpio sobre 10 ficheros.
  - Probes (3 POSTs respetuosos pageSize=3, 200): `ERC Starting Grant` → callIdentifier `ERC-2018-STG` + status `31094503`; `MSCA` → `HORIZON-MSCA-2024-INCO-01` status `Ongoing` (callTitle null, fecha `+0100`); `Creative Europe` → FAQs sin identifier (el parse los descarta).
  - Prune: `erc_calls.py` + `horizon_sedia.py` borrados (sin fallback: transporte único verificado); tests de pinning migrados (028 quita msca, 039 excluye creative de asserts html, new_connectors/parsers a clases v2).
  - Nota: `test_seed.py`+`test_api.py` en orden seed→api da 3 fallos 404 por contaminación de DB entre ficheros (orden artificial; en orden default y suite completa todo verde — 1661 passed). `status:["Ended"]` no está en el set cerrado de `_is_openish` heredado (se filtra por deadline pasada cuando hay fecha; seguimiento posible).
  | key | términos | filtro programa | seed |
  |---|---|---|---|
  | erc-calls | ERC Starting/Consolidator/Advanced/PoC + European Research Council | id `ERC*`, `\bERC\b`, phrase ERC | api (sin cambio) |
  | horizon-europe-sedia | Horizon Europe, open call, research and innovation, 2026, 2027 | catch-all: rechaza lo que ERC/MSCA/CREA reclaman | html→api, base F&T |
  | msca-funding | MSCA, Marie Skłodowska-Curie, Postdoctoral, Doctoral Networks, Staff Exchanges | id `MSCA*`/`HORIZON-MSCA*`, `\bMSCA\b` | html+ConfigurableHtml→api |
  | eu-creative-europe-calls | Creative Europe, CREA | id `CREA*`, `\bCREA\b`, phrase | html+ConfigurableHtml→api |

## Next step
- F1: conector F&T v2 parametrizado (writer).
