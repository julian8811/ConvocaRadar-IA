# Panel reestructurado + bugs de métricas — feature ODD

## Objective
Panel que muestra números reales y solo bloques útiles: KPIs con conteos DISTINCT, definiciones únicas, banner de fuentes sin muertos, compatibilidad alcanzable y matriz fuera del home.

## Problem (auditoría 2026-10-12, solo lectura)
1. **Total 27.637 inflado**: `get_health_kpis` (`services/dashboard.py:349-412`) cuenta sobre `LEFT JOIN OpportunityScore` sin DISTINCT; `OpportunityScore` no tiene UniqueConstraint `(opportunity_id, organization_id)` y cada `scores` inserta fila nueva (`scoring.py:320-333`). Fan-out ~9x. `high_match` sí usa distinct → por eso queda bajo.
2. **Embeddings 155.6%**: numerador sin filtro de fecha vs denominador con `exclude_closed` (`dashboard.py:462-533` vs `search.py:123-129`). Resto del strip con scopes mixtos.
3. **Alta compatibilidad 0**: umbral high ≥75 (`scoring.py:123-135`) inalcanzable con datos ralos (techo ~70 sin monto/fecha); `score-all` procesa de a 10 (`genai.py:93-98`).
4. **Tres "cierran pronto" distintos**: KPI por `status` almacenado vs Pipeline 30d vs Triage 7d. Mismo rótulo, tres cosas.
5. **Tarjetas duplicadas en cliente**: "Cierres en 7 días" = "Atención inmediata" (`TriageZone.tsx:246-247`); "Prioridades visibles" no son prioridades.
6. **Banner cuenta deshabilitadas** (`dashboard.py:561-562` sin filtro `enabled`) y criterio stale marca fuentes lentas; `/sources` incluye `idle` → dos números distintos para lo mismo.
7. **Matrix decorativa**: muestra matches (no oportunidades), sin empty-state, 3 round-trips; título hardcodea 4×6.
8. **PipelineZone con código muerto**: `ClosingSoonGrid` + `top_scored` sin render; charts Score/Funding vacíos con 0 datos.

## Why
Pedido explícito: el panel no actualiza (ya resuelto con T2) y muestra información innecesaria — reestructurar.

## Scope
- IN: fixes backend (DISTINCT, unique constraint + migración, scopes consistentes + clamp, unificar definición cierran-pronto, excluir disabled/idle, umbral high 60 + corrida score-all), restructure home (secciones abajo), mover Matrix a reports, tests + verify.
- OUT: reescribir scoring completo; SSE; gestión de usuarios.

## Nuevo layout propuesto (pendiente sign-off)
1. Hero (igual) + 4 KPIs reales: Total, Abiertas, Cierran en 7 días, Alta compatibilidad.
2. "Qué hago hoy" (cola En revisión + cierres 7d).
3. "Cierran en 7 días" (lista real, única definición).
4. "Salud de fuentes" (solo degraded/failing activas, con link a fuentes).
5. "Calidad de datos" (scopes consistentes, sin >100%).
6. Analítica colapsada: Estado / País (charts con mismo scope).
7. Matrix → `/reports`. Tabs Score/Funding ocultos hasta tener datos.

## Constraints
- TDD en fixes backend; suites dashboard verdes; sin cambiar endpoints públicos (mismos shapes, valores corregidos).
- Migración con UniqueConstraint: verificar duplicados existentes antes (cleanup documentado).
- Commits Conventional; deploy patrón E19–E24. Push/merge decide el usuario.

## Tasks
- [x] **R1 (P1 writer)** ✅ 2026-10-12 DISTINCT en KPIs + unique scores (migración 0018, sin borrado) + scopes consistentes con clamp + banner sin deshabilitadas. 6 passed + vecinas 35; spot-check padre 6 passed. Gap: `calculate_score` hace blind-insert → 500 con el constraint (va en R2 como upsert).
- [x] **R2 (P1 writer)** ✅ 2026-10-12 Upsert en `calculate_score` (con `db.new` por autoflush off) + umbral high 60. 63 + 239 passed; 2 pines viejos ajustados por el padre; spot-check 284 passed. Score-all masivo queda para R4.
- [x] **R3 (P1 writer)** ✅ 2026-10-12 Home reestructurado (sin duplicadas, Matrix→reports con empty-state, tabs condicionales, criterio único). Matrix removido del home por el padre. Suite 108 passed + tsc/eslint limpios.
- [ ] **R4 (P1)** Deploy + verify (cleanup duplicados → migración 0018 → score-all → números reales antes/después).
- [ ] **R4 (P1)** Deploy + verify en servidor con números reales antes/después.

## Acceptance
- Total ≈ suma breakdown; ningún % >100; banner = solo activas con problema real.
- Home sin tarjetas duplicadas ni bloques en 0 decorativos.
- Suite verde; visual verificado.

## Progress
- 2026-10-12: doc creado con auditoría read-only. Mirror Engram pendiente.

## Next step
- Sign-off del layout → R1.
