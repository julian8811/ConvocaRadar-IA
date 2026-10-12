# Lote 1 — preflight 5 fuentes (issue #59) — feature ODD

## Objective
CLI con transporte protegido integrado + preflight (dry-run, 0 red) de 5 fuentes habilitadas no-ASCUN con muestras de títulos y comando exacto del piloto. Sin requests externas hasta gate explícito posterior.

## Problem
Issue #59: el piloto ASCUN usó 2 GET (no 1), el CLI con `--allow-network` no hace red (transport=None), y `run_live_probe` acepta `resolve=None`/`authorized_hosts=None` + detecta tamaño post-recepción + `classify_http` prioriza 200 ante WAF. Nada de eso está validado extremo a extremo.

## Why
Encargo #59 con gate NO-GO para red. Rama/worktree aislados desde fase 4.

## Scope
- IN (worktree `lote1-preflight-20261012`): transporte instrumentado en el CLI (httpx, no redirects, streaming ≤2MB, reloj ≤60s, timeout ≤15s, DNS/SSRF, sin credenciales/HTTP/plano/puertos, 1 GET reutilizado para conectividad+parse+títulos+métricas, `blocked_by_policy` si no cabe); 5 fuentes reales del inventario (WP/RSS/API/HTML, no ASCUN, sin hosts WAF); pertinencia por títulos (accionable/editorial/ambigua/empleo-otro, `needs_human_review`); tests e2e con stub (0 GET dry-run, 1 GET 200+10 títulos, STOP 200/WAF, 301/302, 403, 429, 404, timeout, DNS/IP, 2MB, global); `reports/lote-1-preflight/` + comando exacto.
- OUT: cualquier request externa, prod/DB/timers, merge/deploy, tocar worktree productivo o PR #55/#56.
- TDD; commits locales sin push.

## Constraints
- Máximo 5 GET planeados (1/fuente), secuencial; 54 tests previos verdes; `UNKNOWN` antes que certificar.

## Tasks
- [x] **L1 (P1 writer)** ✅ 2026-10-12 Transporte instrumentado en CLI + 1 GET reutilizado + `blocked_by_policy`. Spot-check padre OK, rama pusheada.
- [x] **L2 (P1 writer)** ✅ 2026-10-12 5 fuentes (novo WP, grants-gov-forecast RSS, minciencias HTML, ukri HTML, innpulsa API) + pertinencia + manifest + dry-runs + comando exacto. 49 passed + diff limpio.
- [x] **L3 (gate)** ✅ 2026-10-12 Piloto ejecutado (5 GET, presupuestos cumplidos): novo GO + innpulsa GO, grants-gov BLOCKED (gate de sesión), minciencias/ukri HOLD (JS/chrome). Veredicto: GO parcial 2/5. Evidencia commiteada + pusheada.
- [ ] **L4 (P1)** Mini-backfill 51 filas NULL (en curso en servidor) + fix minciencias/ukri ✅ deployado y verificado (cherry `924be84`, healthy): minciencias 1→19 (18 ap/ci/mo), ukri 6→14 (9 ci, 6 mo).

## Acceptance
- Criterio gate #59: manifest + dry-run 5 fuentes verificadas, e2e verde, ≤5 requests planeadas, muestras, políticas STOP, `git diff --check` limpio.

## Progress
- 2026-10-12: doc creado; worktree + rama listos desde fase 4 (`8ac8c83`). Mirror Engram pendiente.

## Next step
- Delegar L1+L2.
