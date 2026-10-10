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
- [ ] **E2 (P1)** Verify live en servidor: rebuild + reseed + runs por fuente; medir cobertura open/close/monto en las piloto. Ruta: padre.
- [ ] **E3 (P1)** Decisión de escala con el usuario (todas vs tanda 2) según números del piloto. Ruta: padre inline.

## Acceptance
- Piloto: ≥70% de sus oportunidades con close_date y monto donde la página de detalle los publica; suite verde; nada fuera del piloto afectado.

## Progress
- 2026-10-10: doc creado. Mapa explorer completo (candidate→runner→opportunity, helpers en common.py, piloto propuesto). Mirror Engram pendiente.

## Verification evidence
- (pendiente E1)

## Next step
- E1: writer implementa el piloto.
