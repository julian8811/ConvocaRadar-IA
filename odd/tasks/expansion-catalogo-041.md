# Expansión catálogo 041 (issue #62) — feature ODD

## Objective
Primera tanda de 8–12 fuentes nuevas verificadas (accionables, sin duplicados) con matriz, evidencia, conectores, fixtures y tests. Sin activar, sin cron, sin merge/deploy.

## Problem
Issue #62: no hay lista aprobada post-203; 15 candidatos P0–P2 con notas de dedup (NIH→filtro grants-gov, LIFE→solapamiento eu-funding, etc.). Lotes 039/040 como precedente (`test_039/040_batch_seeds.py`).

## Why
Encargo #62 del dueño. Rama/worktree aislados; remediación #61 en paralelo sin bloquearse.

## Scope
- IN (worktree `expansion-catalogo-041`): A inventario exacto 203 (AST) + dedup; B investigación portales (cortesía: pocos GETs secuenciales, UA repo); C tanda 8–12 verificadas (si menos aptas, reducir con justificación); D matriz CSV/XLSX/JSON; E seed code + tests (fuentes `experimental`/deshabilitadas, fixtures primero); F manifest/dry-run + gates.
- OUT: activación, cron, llamadas masivas, prod/DB, push/merge/deploy, tocar #61.
- TDD; commits locales sin push.

## Constraints
- Estados `candidate/approved/staged/deployed/verified`; cero "agregadas" sin commit+deploy/verify; no confundir con remediación.

## Tasks
- [x] **X1 (P1 writer)** ✅ 2026-10-13 Inventario + dedup + 15 portales + matriz triple formato.
- [x] **X2 (P1 writer)** ✅ 2026-10-13 Tanda 5 (reducida 8→5 justificada): fontagro, fundación-biodiversidad, eu-life-cinea, biodiversa, fondo-acción — `experimental`, sin activar. Spot-check padre 20 passed + diff limpio. Rama pusheada.
- [x] **X3 (gate)** ✅ 2026-10-13 Candado `enabled=False` + gate anti-activación + vigencia/pertinencia/duplicados (16 passed). Piloto 5 GET: eu-life GO, fundación-biodiversidad GO parcial, fondo-acción GO con nota, fontagro/biodiversa HOLD. 0 duplicados vs 203. Spot-check padre OK, rama pusheada. Detenido tras el piloto (sin merge/deploy).
- [x] **X4 (P1 writer)** ✅ 2026-10-13 Evidencias versionadas + conectores LIFE/FB (vencidas, pertinencia, dedup) + rollback + plan de activación por etapas. 34 passed, rama pusheada. `enabled=False` intacto en las 5. Paquete listo para gate de activación.
- [x] **Etapa 0+1** ✅ 2026-10-13 Preflight verde (42 passed); 2 GETs ejecutados: CINEA HOLD (calls 2026 vencidas, 0 abiertas) + FB HOLD (sin fechas en listado + solape BiodivFuture/biodiversa). Criterio GO no alcanzado → etapa 2 NO autorizada. Rama pusheada.

## Acceptance
- Criterios #62: expansión neta probada, accionables verificadas, trazabilidad, gates respetados.

## Progress
- 2026-10-13: doc creado; worktree + rama listos desde `origin/main`. Mirror Engram pendiente.

## Next step
- Delegar X1+X2.
