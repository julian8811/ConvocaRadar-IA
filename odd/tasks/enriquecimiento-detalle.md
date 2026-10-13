# Enriquecimiento de detalle (fechas + montos) — feature ODD

## Objective
Elevar la cobertura de `open_date` (22%), `close_date` (40%) y `funding_amount_value` (9%) sobre ~3.097 oportunidades, entrando a la página de detalle de cada convocatoria. Resumen ya está en 100% — no se toca.

## Problem
El runner (`app/scraper/runner.py:106-249`) publica el candidato tal cual: fechas/montos solo existen si el conector los seteó en la página de listado o si el thin-fill los pescó del texto. Existe `enrich_candidates_batch` (`app/connectors/common.py:2215-2247`, fetch concurrentes + `apply_extracted_fields`) pero solo la usa `uniandes-investigacion`. `ConfigurableHtmlConnector` es list-page-only (sin seguimiento a detalle).

## Why
Pedido explícito del usuario: apertura, cierre, montos, resúmenes e info clave por fuente para el informe.

## Scope
- IN: piloto en 3-5 fuentes (candidatas: ascun-convocatorias WP, minciencias, innpulsa; alternas: simpler-grants/grants-gov) + tests + verify live por fuente en servidor.
- OUT: las demás fuentes hasta validar el piloto; cambios globales de fetch/timeouts; tocar resumen (ya 100%).
- Decisión pendiente del usuario: escalar a las 203 tras el piloto.

## Constraints
- Strict TDD (RED→GREEN→REFACTOR, pytest en apps/api).
- Cortesía de scraping: reutilizar `enrich_candidates_batch` (timeout 15s, límite `extraction_detail_limit`, sin render salvo fallback existente); nada de loops sin cota.
- Commits Conventional directos a main + push (autorizado por el usuario en este flujo); port a servidor vía cherry-pick + rebuild + reseed + verify por fuente.
- Servidor: solo runs acotados por fuente para verificar; secretos nunca fuera.

## Tasks
- [x] **E1 (P1 writer)** ✅ 2026-10-10 Piloto cableado a nivel runner: `enrich_pilot_candidates` en common.py (gate `DETAIL_ENRICHMENT_PILOT_KEYS` = ascun-convocatorias/minciencias/innpulsa, solo fetchea candidatos sin open/close/funding, merge gap-fill vía `enrich_candidates_batch`) + hook en `runner._scrape_candidates` con stat `detail_enriched`. Runner-level porque ascun en vivo resuelve al WordPressGrantsConnector compartido (edición de conector contaminaría). RED ImportError pre-símbolo / GREEN 12 passed + triangulación 149 + 59 passed.
- [x] **E2 (P1)** ✅ Verify live: ganancia 0 con forense (ascun=noticias, innpulsa SSR vacío, minciencias 0 found). Mecanismo E1 validado; falta lado contenido.
- [x] **E4 (P1 writer)** ✅ 2026-10-10 Vuelta 2: innpulsa fechas/monto vía payload API (`_api_first_date` + `_api_funding`, sin fetches nuevos); gate ascun→grants-gov (verificado offline); minciencias DICTAMEN (sin HTML live no se toca). RED 5 failed / GREEN 23 + triangulación 143 + 48 passed.
- [x] **E3 (P1)** ✅ Decisión de escala: tanda 2 elegida por evidencia (padre): world-bank-procurement (377 sin mo; notice_text mina 3/20 con valores limpios), novo-nordisk-grants (111 sin mo, WP SSR completo), simpler-grants (74 sin mo, detail URLs estables). Fapesp descartado (sin conector dedicado; tocar el genérico contamina).
- [x] **E10 (P1 writer)** ✅ 2026-10-10 Tanda 2: world-bank notice_text→funding en parse (19 líneas, 0 fetches, RED 2 failed/GREEN 21 + 76 passed); novo DICTAMEN (ACF desconocido, sin fixtures reales); simpler DICTAMEN (montos ya capturados en parse, detail es shell XHR). Lección ascun aplicada: sin evidencia de contenido no hay código.
- [x] **E11 (P1 writer)** ✅ 2026-10-10 Tanda 3: fapesp al gate (SSR batch existente) + devaid render-step (cap 5, challenge-guard, gap-fill) + cost-open-calls DICTAMEN (URLs nav-junk). BONUS: fix crash regex bolsa sin capture-group que anulaba merges. RED 0/1 / GREEN 10 + 67 + 47 + 115 passed. Deployado cherry `38e3a46`.
- 2026-10-10: E11 verificado por padre en plataforma (sesión consultor): fapesp success 50/50 → ci 114/115 (fechas rindieron); devaid degraded 0 (sitemap devuelve vacío CF — `detail_enriched:0`, hook presente pero sin candidatos; bloqueo a nivel listado, fuera de E11). Nota: runs >~30s dan 500 cosmético en cliente pero completan en servidor (proxy reset) — fapesp completó igual.
- [x] **E12 (P1)** ✅ 2026-10-10 Tanda 4 toda-DICTAMEN (sin código, lección ascun): sdde=documentos PDF (requiere pipeline PDF-texto, fuera de scope), unwomen=secciones sin datos extraíbles (+35 URLs NULL), adaptation-fund=URLs nav-junk (parse-quality, fuera de scope).
- [x] **E13 (P1)** ✅ 2026-10-10 Tanda 5 forense: idt-noticias=noticias (dictamen), idartes=shell incluso renderizado (dictamen), simpler=fechas completas+montos ausentes (dictamen), grants-gov-forecast=sin IDs numéricos + key-wall (dictamen). Sin código.
- [x] **E14 (P1 writer)** ✅ 2026-10-10 Tanda 6: secihti + unal al gate (solo keys + comment, RED 0/3 → GREEN 3 + 33 + 16 passed). Funding dictamen documentado. Deployado cherry `9f60f69`. Verificado por padre: secihti success 36/36 (ap2/ci2), unal success 37/37 (ap0/ci4) — marginal, el contenido detallado rara vez trae más.
- [x] **E15 (P1 padre)** ✅ 2026-10-10 Tanda 7 toda-DICTAMEN (sin código): segib-noticias=noticias (1/1/0), rhodes=program pages sin datos (0/0/0), finep=API sin montos (ap29/ci22/mo1 — fechas OK por F3). Toda fuente ≥15 sin-mo tiene veredicto.
- [x] **E16 (P1)** ✅ 2026-10-11 Barrido LLM sistemático completo: big run --limit 900 --sleep 15 en servidor (180/180, `Summary: scanned=900 filled_dates=25 filled_funding=13 skipped=862 short_text_skipped=79 failed=0`, 38 fills). Cobertura server: TOTAL 3097 AP 726 (+17) CI 1242 (+0) MO 360 (+7).
- [ ] **E18 (P1 forense)** Detalle por fuente: novo-nordisk (111 CI+MO), fondo-emprender (48 CI), fapesp-monto (114 MO). Código solo donde la ficha rinda.
- [x] **E19 (P1 writer)** ✅ 2026-10-11 3 FIX E18 con TDD: novo header/sidebar + DKK en extractor (con guard allowlist), fondo `extract_fondo_detail_fields` + `date_labels`, fapesp estipendio documentado + pines. Tests: `test_enriquecimiento_e19.py` 16/16 (RED 8 failed → GREEN), triangulación 27 + 125 passed; 2 pines viejos en `test_enrichment.py` actualizados por el padre (novo→danida como ejemplar no-piloto), spot-check 28 passed.
- 2026-10-11: E19 deployado en servidor (cherry `d8c2137` solo-código, rebuild healthy, reseed 203 updated). Verificado live: novo 0→2 ci/mo (mecanismo OK, cobertura 2/111); fondo sin cambio (0/48); fapesp +9 ítems/+9 ci pero mo 1 (stipend no aplicado).
- [x] **E20 (P1 writer)** ✅ 2026-10-11 Causas + fix cobertura: fondo fuera del gate (agregado) + batch secuencial anti-starvation (budget 1-2 slots colapsaba los 25 concurrentes). Tests 35 passed + triangulación 43/100/73; spot-check padre 35 passed. Cobertura progresa run a run (~5 runs para novo 111).
- 2026-10-11: E20 deployado (cherry `8d96989` solo-código, rebuild healthy, reseed 203). Verificado live: novo 2→25 ci / 2→22 mo; fondo ap/ci 2→27; fapesp ap 22→43, mo 1→19. Global: TOTAL 3106 AP 772 CI 1301 MO 400.
- [x] **E21 (P1 forense)** ✅ 2026-10-11 Tanda 2: eurimages DICTAMEN (WAF 403 en listado), camara-bucaramanga DICTAMEN (programas permanentes sin fechas), unitar FIX (ficha `event.unitar.org` con Deadline/Date/Price estables).
- [x] **E22 (P1 writer)** ✅ 2026-10-11 Extractor unitar host-gated + gate key, TDD (RED 11 failed → GREEN 12 passed). Corrección honesta: `$` bare da moneda None (precedente fondo). Spot-check padre 24 passed.
- 2026-10-11: E22 deployado (cherry `fed860e` solo-código, rebuild healthy, reseed 203). Verificado live: unitar ap 4→14, ci 5→15 (+10/+10); mo +0 por merge (E23 deployado como `9a566a1`, código activo pero filas con valor y sin moneda no se rellenan).
- [x] **E24 (P1 writer)** ✅ 2026-10-11 Regla general de moneda en `_update_opportunity` (rellena currency/raw faltantes con gate de coincidencia; nunca overwrite). TDD RED 4 failed → GREEN 7 passed + triangulación 228; spot-check padre 7 passed.
- [x] **E25 (P1 writer)** ✅ 2026-10-13 Gate extendido a ascun/cost/sdde (top unknown-sin-close) + backoff 429 en `_call_llm` (3 reintentos + fallback). 11 passed + pines E11/E4 actualizados por el padre (cost/ascun ahora IN gate; exemplar danida). Spot-check 32 passed.
- 2026-10-11: E24 deployado (cherry `419cc0e` solo-código, rebuild healthy, reseed 203). Verificado live: unitar con_moneda 0→10; 8 filas con incoming distinto quedan intactas por diseño (gate anti-mezcla).
- 2026-10-13: tema fechas sin-cierre cerrado: allow_past en merge (uniandes cierra), extractor deadline-regist (unitar), backfill dirigido 2/2 (closed 2026-10-02 y 2026-09-24); residual honesto 10 self-paced + titulares sin fecha.
- [x] **E23 (P1 writer)** ✅ 2026-10-11 Regla unitar bare-`$`→USD (decisión usuario documentada, alcance solo-host, regla global intacta + pin). TDD RED→GREEN, 13 passed; spot-check padre 25 passed.
- [x] **E17 (P1 padre)** ✅ Proveedor Groq cableado (llama-3.3 retirado → gpt-oss-20b vía /models), recreate, probe OK.
- [x] **E7 (P1)** ✅ Vía XHR sin key (reemplaza Simpler-key): `POST apply07.grants.gov/grantsws/rest/opportunity/details` form `oppId=` → 200 keyless con awardCeiling/Floor/estimatedFunding/synopsisDesc (12.5KB). Descubierto por intercepción Playwright del tráfico real de la ficha.
- [x] **E8 (P1 writer)** ✅ 2026-10-10 Detail-XHR awards: `enrich_grants_gov_funding_xhr` (form POST keyless, cap 25, concurrencia 5, gap-fill, never-raise) cableado ANTES del render E6. RED ImportError / GREEN 7 + 32 + 85 passed. Fix anidado `synopsis.*` verificado live (364026 → USD 62.5M). Deployado cherry `009f888`, api+worker sanos. E2c: grants-gov mo 0→19 (raw 23) en 1 run — PRIMERAS GANANCIAS. Resta iterar (cap 25/run).
- 2026-10-10: E2c run 2 sin ganancia (25 updated, mo 19). Forense: top-25 fijos ya fondeados; 73 viejos fuera de ventana nunca reintentados. Probe live 8 unfunded → 6 CON awards (62500000, 750000, 13M, 3.5M...). Vía: backfill directo E9.
- 2026-10-10: E10 verificado live — world-bank success (93 found/50 updated), mo 103→105 (+2 marginal: los avisos vigentes rara vez traen monto). Global mo 277→341 (+62: grants-gov 60 + WB 2). E3 escalar: pendiente decisión con estos números.
- [x] **E9 (P1 writer)** ✅ 2026-10-10 Script `scripts/backfill_grants_gov_awards.py` (--dry-run default, --limit 25, --sleep 1.0, batches de 5, gap-fill puro compartido). RED FileNotFoundError / GREEN 6 + 8 E8 + 33 funding passed. Deployado cherry `fecfc64` (vía stdin: rootfs read-only impide docker cp). Aplicado 3×25: 45 filled → grants-gov mo 0→60/92 (65%), global mo 277→339.
- [x] **E5 (P1)** ✅ Extracción LLM Gemini cableada y probada en vivo: `.env` (LLM_PROVIDER=gemini, base OpenAI-compat, model gemini-3.8-flash — 2.0 retirado), recreate api+worker, probe sintético exacto (provider google, conf 0.9, open/close + 500M COP). Dry-run real: innpulsa 5 muestras (fechas buenas 0.68-0.95, montos ausentes en texto) + grants-gov 3 muestras (nada en synopsis). Veredicto: mecanismo OK, las fuentes no traen montos en el texto disponible.
- [x] **E6 (P1 writer)** ✅ 2026-10-10 LLM sobre ficha renderizada: `enrich_grants_gov_render_llm` en common.py (render 15s best-effort + determinísticos + Gemini gap-fill, cap 10 renders/run, solo grants-gov sin funding). RED ImportError / GREEN 9 + 37 + 327 related passed. Deployado (cherry `244e5df`, rebuild api+worker sanos).
- 2026-10-10: E6 veredicto live — render funciona (55KB) pero la ficha sigue siendo cascarón (2544 chars boilerplate, 0 `$`/deadline/eligib): la app Angular carga el dato por XHR posterior. Ni SSR ni render alcanzan; vía real: API de simpler.grants.gov o XHR de la ficha. E3 sigue bloqueado.

## Acceptance
- Piloto: ≥70% de sus oportunidades con close_date y monto donde la página de detalle los publica; suite verde; nada fuera del piloto afectado.

## Progress
- 2026-10-10: doc creado. Mapa explorer completo (candidate→runner→opportunity, helpers en common.py, piloto propuesto). Mirror Engram pendiente.
- 2026-10-10: E1 completo + commit `bd11401` pusheado + cherry-pick `a260290` + rebuild api en servidor (gate piloto verificado vivo). Baseline piloto: ascun 67 (ap67/ci0/mo0), innpulsa 68 (ap68/ci68/mo4), minciencias 1 (todo 0). E2 pendiente: medir tras el barrido en curso del usuario.
- 2026-10-10: barrido `b642c8ee` 203/203 success pero cobertura piloto INTACTA. Hallazgo: el scraping real corre en el worker, que tenía imagen pre-E1 (ImportError del gate) — rebuild worker + verificado gate vivo. E2 pendiente: correr las 3 piloto individualmente y medir.
- 2026-10-10: E2 veredicto HONESTO — ganancia 0. ascun 188 found/50 updated sin ci/mo; innpulsa 73/50 sin mo nuevo; minciencias degraded 0 found. Forense: (1) ascun trae NOTICIAS (/noticias-ies/), no convocatorias — piloto equivocado, 64/67 URLs NULL de la era pre-WP; (2) innpulsa detail SSR es shell JS (título genérico, sin fechas/montos en HTML — probe live `enrich_from_detail_page` devuelve dict vacío de campos); (3) minciencias rinde 0 — listing `/convocatorias/todas` devuelve stub de 46 bytes (sin anchors; probable challenge/JS) — requiere render opt-in (patrón F2 danida).
- 2026-10-10: E4 deployado (commit `d01e952` + cherry `b6d35f6`, rebuild api+worker, gate grants-gov/innpulsa/minciencias verificado vivo). E2b pendiente: runs innpulsa + grants-gov y medir.
- 2026-10-10: E2b veredicto — innpulsa 73/50 y grants-gov 25/25 re-scrapeados, mo sigue igual. Forense live: payload innpulsa (77 ítems) NO trae ningún campo de monto (solo beneficiaries_count=cupos, no dinero); text-mining da 4 falsos positivos (1.0/50.0/30.0 sin moneda). grants-gov search API no devuelve awardCeiling/Floor (raw=0). Conclusión: montos no recuperables por scraping en estas fuentes con precisión aceptable. E3 (escala) bloqueado hasta definir método.

## Verification evidence
- (pendiente E1)

## Cierre
- 2026-10-10: feature completo. Global: mo 277→341 (+64), ap 689→691, ci 1233→1235, res 100%. Grants-gov 0→60 (backfill XHR), WB +2, fapesp ci 114 (fechas). Toda fuente ≥15 sin-mo con veredicto (built: grants-gov/WB/fapesp/secihti/unal; dictamen: ascun-news, innpulsa-mo-ausente, minciencias-stub, devaid-CF, cost/adaptation-junk, novo-ACF, simpler-shell, sdde-PDF, unwomen, idt-news, idartes-shell, segib-news, rhodes, finep-mo, grants-forecast-keywall). E3 cerrado: escala por tandas completada; resto es cola <15 con retornos marginales.
