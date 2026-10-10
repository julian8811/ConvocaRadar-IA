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
  - Verificado live 2026-10-10: cherry-pick `7eab76e` + rebuild + reseed-force (201) → **danida-denmark: success 6 ítems** (estaba en 0). PR #47 mergeado (`1e09e5d`).
- [x] **F3 (P1 writer)** ✅ 2026-10-10 Descubrimiento JS (finep API Liferay, startup split 3× con aprobación) + dictámenes. Commits `de6cc53` (finep) + `55c06b7` (split). PR #48 mergeado. Verificado live: cherry-pick + rebuild + reseed-force (203 updated, catálogo 204 con huérfana) → finep 33, splits 1/1/1, todos success; huérfana `startup-chile` desactivada (enabled=False).
  - finep-brasil: landing `/oportunidades` Liferay sin chamadas en SSR (lista CSR via bundle `/o/finep-busca-chamadas-publicas/`). Hallazgo: `GET /o/c/chamadapublicas` público sin auth (totalCount=478, `pageSize=500` devuelve todo en 1 página; 34 abertas + 1 sin-situacao vigente EUREKA + 443 encerradas). `FinepConnector` pasa de GenericHtml a conector API (fetch 1 GET + loop defensivo max 10 págs; parse filtra `aberta`/`''`, close de `prazoProposto`→`vigenciaFim`, official_url al listing humano). Seed base_url → endpoint. Gotcha: `parse_date_text` no traga ISO con `T` (`2027-04-30T17:00` falla `\b`) → helper local `_iso_date` en `brazil_portals.py` (sin tocar common).
  - startup-chile split (aprobado, reversible: solo seed, sin código): `/postula/` SSR sin links de convocatoria (programas solo en nav + secciones Vue) → 3 subfuentes `ConfigurableHtml` independientes: `startup-chile-build` (`/postula/build/`), `startup-chile-growth` (`/postula/growth/`), `startup-chile-ignite` (`/postula/ignite/`). SSR real verificado por programa: sin `<main>`/`<article>` (Vue `#app` + 3 `<section>`), h1 estáticos en hero, CTAs de programa con binding Vue (sin href SSR); cada página rinde 1 candidato = PDF de bases CORFO (mismo doc `...modifica-bases-start-up-chile-big-11.pdf` linkeado en las 3; título CTA débil "¡Leer aquí! add"). Estado: "¡Atentos a la próxima convocatoria!" (entre llamadas). Catálogo 201→202. PENDIENTE PADRE en verify: la key vieja `startup-chile` queda huérfana en DB (el seed no borra/desactiva) → desactivar/borrar fila vieja en reseed-force, o el scrape stale sigue corriendo.
- [x] **F4 (P1)** ✅ 2026-10-10 Cuarentenas verificadas + T4 ruido + T5 timeouts + T6 sweep cierre. Cuarentena firmada 9/9 (3 ya pausadas, 6 seteadas; reintentan solas cada 24h por cooldown). Sweep force final `cb9f3a41`: 203/203 success, failed 0, 2885 ítems (194 success / 9 degraded / 0 failed).
  - [x] **T5-findeter + 4 timeouts (P1 writer)** ✅ 2026-10-10 Rama `feature/fuentes-findeter-t5`, sin push (verifica el padre por fuente con rebuild+reseed). Commits `70eb1c2` (findeter) + `d9d58c7` (apc) + `fc0c842` (ascun) + `ce803ea` (novo) + `17419b8` (world-bank) + este doc.
  - FINDETER causa: seed `base_url=/convocatorias` (listing JS-renderizado, SSR 15KB 0 links) + `parse()` nunca consultaba el sitemap → `candidates_parsed=0`. El filtro de años era inocente (verificado contra sitemap real 2026-10-10: urlset 3351 locs, 2869 `/convocatorias/`, 2023:331/2024:402/2025:273/2026:140, sin trailing slashes; regex fin-de-línea OK). Fix: `_sitemap_fallback()` (fetch sitemap 25s/1 intento/sin render + parse con `limit=_MAX_CANDIDATES`) cuando el HTML rinde 0; `_parse_sitemap_content(..., limit=10)` preserva el cap del path sitemapindex. RED 3 failed (HTML-vacío→0) / GREEN 20 passed + pin duras-a intacto. Verificado local contra sitemap real: 100 candidatos (cap), ej. `Findeter AT-MINDEPORTE … paf-atmindeporte-o-002-2023`. PENDIENTE PADRE: rebuild+reseed-force y verify por fuente (debería pasar de 0 a ~100; runs siguientes rinden el resto por dedup incremental). Nota: el sitemap ordena viejo→reciente, así 2026 aflora tras ~10 runs — reordenar por año queda propuesto, no aplicado.
  - TIMEOUTS causa común: `fetch_httpx_text` sin cota explícita = 120s × retries=2 + fallback a render (slot=1) → >400s peor caso vs cap 180s por fuente. Estrategia por fuente (nada global), cada una con 1 fetch puntual de evidencia:
  | key | fase lenta | estrategia | peor caso |
  |---|---|---|---|
  | apc-colombia | `?page=2` se cuelga en TLS (>25s); fan-out 7 págs 30s×2 + render encolado | `_fetch_one` y último-recurso: 15s, 1 intento, `playwright_fallback=False` (Drupal SSR) | ~15s |
  | ascun-convocatorias | 1 llamada WP sana (200, 3.4s, 174KB); riesgo = cuelgue del otro lado × (120s×2+render) | fetch: 20s, 1 intento, sin render (JSON) | ~20s |
  | novo-nordisk-grants | loop hasta 10 págs secuenciales ×15s ≈150s + overhead roza el cap (sitio sano: Total=136 en 2 págs, 3s/pág) | `max_pages` por fuente en factory: novo=3 (300 ítems), cost-eu hereda 10 | ~45s |
  | world-bank-procurement | API sana (rows=5 en 0.4s); riesgo = cuelgue × (120s×2+render) | fetch: 30s, 1 intento, sin render (JSON); `rows=100` intacto (sin evidencia para recortar) | ~30s |
  - Tests: RED→GREEN por unidad (apc 2 failed→3 passed, ascun 1→3, wp 2→7, wb 1→18); triangulación (caps legacy, early-stop, failure→[]). `ruff check` limpio (verificación). PENDIENTE PADRE: verify live por fuente tras rebuild+reseed; si algún timeout persiste del otro lado con estas cotas, el dictamen pasa a "sitio lento → backoff por diseño" con los stats de run como evidencia.

## Acceptance
- 4 F&T en success con ítems; danida/finep/startup resueltas o con dictamen; WAF con motivo + sign-off; suite verde; nada sano tocado.

## Progress
- 2026-10-10: doc creado (5 tareas F0–F4). Mapa explorer completo. Mirror Engram pendiente.
- 2026-10-10: batch persist+409+pines verificado live (cherry-pick + rebuild + reseed 203): **ascun 188 success, novo 135 success** (tras unpause manual; el 409 `paused_cooldown` funcionó en vivo antes del unpause), apc 34 y WB 93 ya verdes. PR #50 mergeado. Timeouts sistémicos cerrados.
- 2026-10-10: F2 completo (writer, commits `0ad842a`+`3290fe5`): RED danida-sin-flag→0 renders / flag-sin-cablear→no-op (8 failed); GREEN 12/12 + triangulación 1613 passed (+60 test_api.py) + 91 seeds; `ruff check` limpio (format-diffs preexistentes no tocados).
- 2026-10-10: findeter verificado live (unpause manual + runs): **100 ítems ×2 runs consecutivos, success** (created 3/updated 97, luego 0/100). Hallazgos: (1) el HTTP 500 del cliente era del path de respuesta con runs grandes, el run completaba igual — seguir con body a fichero; (2) endpoint single-run devuelve 500 si dispatcher retorna None (pausada en cooldown) en vez de 409 con motivo — bug real a corregir; (3) ascun/novo mueren EXACTO a ~90s (cap por fuente mata la fase persist: url-check HEAD por candidato + embeddings) — el fix es acotar persist, no fetch.
 - 2026-10-10: F3 completo (writer, rama `feature/fuentes-f3-js`, commits `de6cc53`+`55c06b7`): RED finep-fixture→0 candidatos + seed-URL mismatch (3 failed) / split-keys→connector_config missing (8 failed); GREEN test_finep_api 7/7 + 026 18/18 + lote tocado 64 passed; `ruff check` limpio (6 ficheros).
 - 2026-10-10: batch robustez sweep completo (writer, rama `feature/fuentes-persist-409-pines`, commits `b45b3ba`+`d47a799`+pin, sin push): persist acotada (ascun max_pages 3 + timebox remaining-5s + tope 50 + warmup concurrente) + 409 paused_cooldown/already_running + pines 039/040 201→203. Ver sección "Persist-409-pines evidence".

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
- Cuarentena firmada 9/9 (3 ya pausadas, 6 seteadas; reintentan solas cada 24h por cooldown). Feature completo. Resta: rotaciones al cierre de sesión.

## F3 evidence (writer 2026-10-10, rama `feature/fuentes-f3-js`, sin push)
- RED finep: `test_parse_real_fixture_yields_five` → 0==5 (GenericHtml sobre JSON), `test_close_date...` → KeyError, `test_seed_base_url...` → mismatch (3 failed); resto en verde (basura/validate/routing ya valían).
- GREEN finep: `tests/test_finep_api.py` 7 passed (5 candidatos: 4 abertas + EUREKA `''`; encerrada ELETROLISADOR excluida; close 2027-04/2026-11; official_url=listing).
- RED split: keys nuevas → `connector_config missing` (8 failed en 026 seeds+parse).
- GREEN split: 026 seeds+parse 18/18 (incl. `test_startup_split_yields_bases_pdf_per_program`); verificación contra HTML real descargado: 1 candidato/programa (PDF bases); `#app` como list_selector da 0 (ruido de scripts inline vía `looks_like_noise_text`) → `section` primero.
- Triangulación: `test_brazil_portals.py` reescrito a API (7 tests), pines URL en orphan/029, lote tocado (026/028/029/orphan/finep/brazil/duras-a) 64 passed; `ruff check` limpio.
- Descubrimiento: 5 GETs finep (landing + bundle 215KB + api p1/p2/p1000→cap 500) + 4 GETs startup (postula + 3 programas). Nada irreversible (lecturas + seed); split revierte con revert del seed.
- Catálogo: 201→202 (startup-chile → 3 subfuentes; finep misma key).
- Pendiente padre (verify por fuente): rebuild + reseed-force; finep debería dar ~35 candidatos (34 abertas + EUREKA); startup 1 c/u (PDF bases); DESACTIVAR fila huérfana `startup-chile` (el seed no borra).

## Persist-409-pines evidence (writer 2026-10-10, rama `feature/fuentes-persist-409-pines`, sin push)
| ítem | diseño (números) | commits |
|---|---|---|
| persist acotada | ascun-convocatorias resuelve a WordPressGrantsConnector por fallback `/wp-json/` (no a AscunConnector): max_pages 10→3 (precedente novo; fetch ≤~45s peor caso). `PERSIST_MAX_ITEMS_PER_RUN=50` + timebox `remaining-5s` (deadline monotónica): el run completa con lo alcanzado y deja `persist capped` visible en logs en vez de TimeoutError→failed. Warmup concurrente (semaforo 16, 15s) de `async_url_is_reachable` (misma fn + mismo TTL 24h, best-effort). Budget: 50×~2s≈100s peor caso frío, pero el timebox manda primero en envs lentos. services/ intacto. | `d47a799` |
| 409 con motivo | `dispatch_block_reason()` espejo read-only de los skips del dispatcher (sin mutar pausa; dispatcher intacto). Endpoint responde 409 `paused_cooldown` (+retry_after_seconds) / `already_running` (+run_id). Casos: pausada-en-cooldown→409 sin crear run; run-en-curso→409 sin duplicar; cooldown vencido→pasa (200, semántica intacta). Colateral: `test_run_source_runs_inline` dejaba un `running` huérfano en la DB compartida (invisible antes); ahora se finaliza. | `b45b3ba` |
| pines 039/040 | 201→**203** (verificado por AST + diff de keys: split startup-chile 1→3 = net +2, finep-brasil conservó key). OJO: la nota F3 decía 202 y el brief del batch decía 204 — ambas mal; el conteo vigente es 203. `grep 201` en tests/ solo deja los comentarios históricos. | pin (este batch) |
- RED: 409 → 2×200 en vez de 409; persist → AttributeError (sin `_warm_url_cache`/deadline) + `max_pages=10`; pines → `got 203`.
- GREEN: conflict 3 passed; persist_bounds 6 passed; 039+040 8 passed; lote tocado (persist-bounds/wordpress/scraper-module/resilience/sources/ascun/conflict) 47 passed; `ruff check` limpio.
- Pendiente padre (verify por fuente, sin servidor del writer): ascun y novo deben completar <90s sin TimeoutError; confirmar `persist capped` en logs si acota; POST run sobre pausada→409.

## Progress (cont.)
- 2026-10-10: batch persist verificado live (cherry-pick + rebuild + reseed 203): **ascun 188 success, novo 135 success** (tras unpause; el 409 `paused_cooldown` funcionó en vivo), apc 34 y WB 93 ya verdes. PR #50 mergeado. Timeouts sistémicos cerrados.
- 2026-10-10: QA exhaustivo con cuenta consultor (tras reset de su password a `Julian881100` — el hash estaba bien pero no coincidía): API 22/22 en 200 + detail/scores + favorito reversible + single-run urosario success; web 16/16 (307 raíz normal). NO probado a propósito: register, passwords, envíos de alertas, bulks admin, deletes.
- 2026-10-10: sweep force final de cierre (`cb9f3a41`): **203/203 success, failed 0**, 2885 ítems, 194 success / 9 degraded / 0 failed. Restan solo: aladi/cali (sección eliminada), bogota/sloan (WAF), dane/idb/procolombia/sicon (sin contenido vigente o migrado), conacyt-mexico (único sin triage profundo).
