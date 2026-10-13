# Issue #61 — remediación post-barrido (16+7+8+15) — feature ODD

## Objective
Remediar las 46 no-OK del barrido 203/203 según issue #61, con investigación documental, gate humano antes de red/mutaciones y matriz de remediación exportada.

## Problem
#61 define 4 frentes (A:16 dead, B:7 WAF, C:8 transient, D:15 policy) + calidad de las 157 live_ok como etapa independiente. Reglas: sin red masiva, sin tocar prod, gate explícito antes de GET en vivo/mutación/push/merge/deploy, matriz CSV/JSON/XLSX.

## Why
Encargo #61 del dueño; backlog preparado sin ejecutar. Parte ya corre bajo docs propios (ver mapeo).

## Scope
- IN: mapear frentes a trabajo en curso, completar gaps (matriz exportada, runbook de decisiones), ejecutar solo lo autorizado por gates.
- OUT: red masiva, bypass WAF, desactivar fuentes sin revisión, merge/deploy (gates separados).

## Mapeo a trabajo existente (2026-10-12)
- Frente A (16 dead) → R-B forense completo (16 SEED-STALE, 0 muertas); re-mapeo de URLs en curso (worker).
- Frente D (15 policy) → R-A implementado + re-probe en curso (worker).
- Frente B (7 WAF) → documentar (pendiente, veredicto: sin bypass).
- Frente C (8 transient) → re-probe único pendiente (veredicto).
- Calidad 157 live_ok → etapa independiente (pertinencia por títulos, como lote 1).
- Matriz CSV/JSON/XLSX → pendiente de generar desde evidencia.

## Constraints
- Gate humano explícito antes de GET en vivo, mutación, push/merge/deploy.
- TDD en código; investigación con fuentes oficiales; `not verified` sin adivinar.

## Tasks
- [x] **M0** Mapeo y doc (este archivo).
- [x] **M1** ✅ Workers cerrados: re-mapeo 8 + re-probe 15 + discovery (2 canónicas aplicadas, 4 PENDIENTE honestos).
- [x] **Frente B** ✅ 7 WAF documentadas (cuarentena/contacto/pausa, sin bypass; ANID+Fondecyt candidatas a fusión).
- [x] **Frente C** ✅ Re-probe único (8 GETs): gates-cambridge RECUPERADA; 4 UE POST-only (1 fix las resuelve); 2 TLS persisten; idartes inconclusa (egress IPv6 local).
- [x] **M2** ✅ 2026-10-13 Matriz `matriz-remediacion.{csv,json,xlsx}` (203 filas, conteos reconcilian) commiteada y pusheada.
- [ ] **M3** Fix conector POST UE (4 fuentes) + matriz lista.
- [ ] **M3** Fix conector POST UE (4 fuentes) + matriz lista.
- [ ] **M2** Matriz de remediación CSV/JSON/XLSX + resumen con decisiones aprobadas/pendientes.
- [ ] **M3** Frentes B y C (documentar WAF, re-probe transient) + etapa calidad live_ok (gate separado).

## Acceptance
- Criterios #61: inventario 46 con P0-P3, investigación sin red masiva, propuestas por fuente, gate respetado, matriz exportada, diferencia reachable vs verificada documentada.

## Progress
- 2026-10-12: doc creado; M0 listo. Mirror Engram pendiente.

## Next step
- Cierre de workers → M2.
