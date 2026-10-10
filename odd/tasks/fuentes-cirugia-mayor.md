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
- [x] **F1 (P0 writer)** ✅ 2026-10-10 Conector F&T v2 parametrizado (erc/horizon/msca/creative) con filtros por programa + tests fixtures del probe; conectores viejos pruneados. Commits `cd72be2` (feat: conector unificado + migración) + `af3e181` (refactor: prune v1). PR #46 mergeado (`1b81529`). Verificado live: erc 48, horizon 17, msca 11, creative 27, todos success. Incidente: parsing shell frágil ocultó el run msca (el run SÍ ocurrió); lección: body a fichero + parse python.
- [x] **F2 (P1 writer)** ✅ 2026-10-10 Flag render opt-in en `ConfigurableHtml`: `force_render: bool=False` + `wait_selector: str|None=None` en `HtmlConnectorConfig`/`from_dict`; `fetch` renderiza SIEMPRE vía `render_page_html` (domcontentloaded, 45s, post-wait 800ms) cuando el flag está on, sin gate de tamaño; fallo de render conserva el contenido httpx. Gate `browser_fallback<1500` y slot playwright=1 INTACTOS. danida-denmark: base_url → `/en/danida/calls-for-proposals/` (DynamicWeb currentPageId 10308, GET 200/52KB con `js-dynamic-list-module`, 0 calls en SSR) + `force_render=true`, `wait_selector=.js-dynamic-list-module`. Commits `0ad842a` (flag+12 tests) + `3290fe5` (seed danida). Rama `feature/fuentes-f2-render`, sin push (portea el padre con rebuild+reseed y verifica por fuente).
  - Diseño: opt-in explícito default-off (ninguna de las 10 duras lo tenía; solo danida lo lleva ahora); reemplazo de contenido solo si el render no viene vacío; `wait_selector` best-effort (falla → post-wait, sin romper fetch).
  - RECOMENDACIÓN slot 1→2 (NO aplicada): si el sweep muestra renders concurrentes encolados (timeout "Timed out waiting for a Playwright slot"), subir `playwright: max_concurrent` 1→2 en `domain_budget.py:64`. Costo: ~150–300MB RAM extra por browser concurrente; con Chromium ya en imagen y frecuencia weekly de danida, slot=1 alcanza para F2 — reevaluar solo con evidencia de cola en F3 (finep/startup).
  - Pendiente del padre: verify live por fuente (rebuild+reseed-force; danida debería pasar de 0 a N calls); selectores de lista son best-effort sobre DOM renderizado (ajustar contra snapshot real si el parse da 0).
  - Verificado live 2026-10-10: cherry-pick `7eab76e` + rebuild + reseed-force (201) → **danida-denmark: success 6 ítems** (estaba en 0). PR #47 mergeado (`1e09e5d`).
- [x] **F3 (P1 writer)** ✅ 2026-10-10 Descubrimiento JS (finep API Liferay, startup split 3× con aprobación) + dictámenes. Commits `de6cc53` (finep) + `55c06b7` (split). Rama `feature/fuentes-f3-js`, sin push (verifica el padre por fuente).
  - finep-brasil: landing `/oportunidades` Liferay sin chamadas en SSR (lista CSR via bundle `/o/finep-busca-chamadas-publicas/`). Hallazgo: `GET /o/c/chamadapublicas` público sin auth (totalCount=478, `pageSize=500` devuelve todo en 1 página; 34 abertas + 1 sin-situacao vigente EUREKA + 443 encerradas). `FinepConnector` pasa de GenericHtml a conector API (fetch 1 GET + loop defensivo max 10 págs; parse filtra `aberta`/`''`, close de `prazoProposto`→`vigenciaFim`, official_url al listing humano). Seed base_url → endpoint. Gotcha: `parse_date_text` no traga ISO con `T` (`2027-04-30T17:00` falla `\b`) → helper local `_iso_date` en `brazil_portals.py` (sin tocar common).
  - startup-chile split (aprobado, reversible: solo seed, sin código): `/postula/` SSR sin links de convocatoria (programas solo en nav + secciones Vue) → 3 subfuentes `ConfigurableHtml` independientes: `startup-chile-build` (`/postula/build/`), `startup-chile-growth` (`/postula/growth/`), `startup-chile-ignite` (`/postula/ignite/`). SSR real verificado por programa: sin `<main>`/`<article>` (Vue `#app` + 3 `<section>`), h1 estáticos en hero, CTAs de programa con binding Vue (sin href SSR); cada página rinde 1 candidato = PDF de bases CORFO (mismo doc `...modifica-bases-start-up-chile-big-11.pdf` linkeado en las 3; título CTA débil "¡Leer aquí! add"). Estado: "¡Atentos a la próxima convocatoria!" (entre llamadas). Catálogo 201→202. PENDIENTE PADRE en verify: la key vieja `startup-chile` queda huérfana en DB (el seed no borra/desactiva) → desactivar/borrar fila vieja en reseed-force, o el scrape stale sigue corriendo.
- [ ] **F4 (P1)** Cuarentenas verificadas + T4 ruido + T5 timeouts + T6 sweep cierre.

## Acceptance
- 4 F&T en success con ítems; danida/finep/startup resueltas o con dictamen; WAF con motivo + sign-off; suite verde; nada sano tocado.

## Progress
- 2026-10-10: doc creado (5 tareas F0–F4). Mapa explorer completo. Mirror Engram pendiente.
- 2026-10-10: F0 completo (padre inline). sloan/ccb → cuarentena con motivo (WAF persiste con render); findeter Parisable.
- 2026-10-10: F2 completo (writer, commits `0ad842a`+`3290fe5`): RED danida-sin-flag→0 renders / flag-sin-cablear→no-op (8 failed); GREEN 12/12 + triangulación 1613 passed (+60 test_api.py) + 91 seeds; `ruff check` limpio (format-diffs preexistentes no tocados).
- 2026-10-10: F3 completo (writer, rama `feature/fuentes-f3-js`, commits `de6cc53`+`55c06b7`): RED finep-fixture→0 candidatos + seed-URL mismatch (3 failed) / split-keys→connector_config missing (8 failed); GREEN test_finep_api 7/7 + 026 18/18 + lote tocado 64 passed; `ruff check` limpio (6 ficheros).

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
- F4: cuarentenas verificadas + T4 ruido + T5 timeouts + T6 sweep cierre.

## F3 evidence (writer 2026-10-10, rama `feature/fuentes-f3-js`, sin push)
- RED finep: `test_parse_real_fixture_yields_five` → 0==5 (GenericHtml sobre JSON), `test_close_date...` → KeyError, `test_seed_base_url...` → mismatch (3 failed); resto en verde (basura/validate/routing ya valían).
- GREEN finep: `tests/test_finep_api.py` 7 passed (5 candidatos: 4 abertas + EUREKA `''`; encerrada ELETROLISADOR excluida; close 2027-04/2026-11; official_url=listing).
- RED split: keys nuevas → `connector_config missing` (8 failed en 026 seeds+parse).
- GREEN split: 026 seeds+parse 18/18 (incl. `test_startup_split_yields_bases_pdf_per_program`); verificación contra HTML real descargado: 1 candidato/programa (PDF bases); `#app` como list_selector da 0 (ruido de scripts inline vía `looks_like_noise_text`) → `section` primero.
- Triangulación: `test_brazil_portals.py` reescrito a API (7 tests), pines URL en orphan/029, lote tocado (026/028/029/orphan/finep/brazil/duras-a) 64 passed; `ruff check` limpio.
- Descubrimiento: 5 GETs finep (landing + bundle 215KB + api p1/p2/p1000→cap 500) + 4 GETs startup (postula + 3 programas). Nada irreversible (lecturas + seed); split revierte con revert del seed.
- Catálogo: 201→202 (startup-chile → 3 subfuentes; finep misma key).
- Pendiente padre (verify por fuente): rebuild + reseed-force; finep debería dar ~35 candidatos (34 abertas + EUREKA); startup 1 c/u (PDF bases); DESACTIVAR fila huérfana `startup-chile` (el seed no borra).
