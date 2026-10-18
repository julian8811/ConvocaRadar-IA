# Rendimiento fuentes + fechas por fuente — feature ODD

## Header
Objetivo: (A) deshabilitar fuentes habilitadas con yield cero (ahorro de sweep diario) y (B) subir CLOSE con patrones de fecha por fuente (adaptation/sdde/novo/unitar). Basal prod 2026-10-18: TOTAL=3068 CLOSE=49.6% OPEN=24.9% FUND=16.0% SUM80=56.2%, 201 enabled / 11 disabled, 21 vacías (6 habilitadas).

## Specs
- S1 (verbatim usuario): "qué podemos hacer para optimizarlas"
- S2 (verbatim usuario, scope): "A+B juntos" = (A) apagar lo que no rinde + (B) fechas por fuente adaptation/sdde/novo/unitar.
- S3: todo disable lleva migración con downgrade + test de cadena + verificación en prod (enabled + 0 filas nuevas); toda purga con backup previo (precedente purge-trio).
- S4: todo patrón de fecha lleva test RED→GREEN con fixture real + `git diff --check` limpio; sin push/merge (lo decide el usuario).
- S5: verificación por cobertura real en prod, no solo unitarios.

## Tasks
- [x] **T1** ✅ 2026-10-18 Evidencia yield cero (read-only): dane/idb/sicon con 0 filas + `last_item_count=0` + `empty_runs=5` → disable. ascun: 200 parsed/0 válidos (filtro news) → disable. innovamos-gif/startup-chile (1 ítem reciente) EXCLUIDOS (no probado). `empty_runs=5` es cap, no prueba sola.: `consecutive_empty_runs`, `last_item_count`, `last_run_at`, `last_success_at` de las 6 vacías-habilitadas (innovamos-gif, startup-chile-growth, ascun, idb, sicon, dane) + top `consecutive_empty_runs` global. Solo lectura.
- [x] **T2** ✅ 2026-10-18 Disable dane/idb/sicon/ascun: seed + 0023 + tests (9 passed) + deploy (guard IDLE, rebuild, api healthy) + verify prod (alembic 0023, 4×enabled=False, 0 filas c/u).: seed `enabled=False` + migración 0023 (downgrade) + tests + deploy + verify. Gap-fill: nada que purgar (vacías).
- [ ] **T3** Fechas adaptation-fund (47 noclose): patrones + fixtures + tests.
- [ ] **T4** Fechas sdde-bogotá (44 noclose): patrones + fixtures + tests.
- [ ] **T5** Fechas novo (33) + unitar (21): patrones + fixtures + tests.
- [x] **T6** ✅ 2026-10-18 Purga-dos ejecutada (backup 47+35 verificado, dependents 82+82, DEL exactos, REMAIN adap 0/sdde 13 con 9 avisos). GLOBAL: TOTAL=2986 CLOSE=1521 (50.9%) OPEN=763 (25.6%) FUND=488 (16.3%) SUM80=1719 (57.6%). Deltas vs basal T1 (3068/49.6/24.9/16.0/56.2 tras T2): CLOSE +1.3pp, resto estable; el grueso del gain de CLOSE vino del purge-trio previo. Novo/unitar: sin acción (archivados/vigentes, nada extraíble sin fabricar).

## Veredictos T3–T5 (evidencia, 2026-10-18)
- T3 adaptation-fund (47 noclose): 100% chrome del sitio (sectores, vistas, about, COPs, contact) — CERO calls. Sin patrones que escribir; corresponde purga con backup.
- sdde-bogotá (44 noclose): convenios/contratos firmados 2021-2023 + ~6 avisos LP 2025-2026. Son actas de contratación, no convocatorias con deadline. Decisión de scope pendiente.
- novo (33 noclose): grants reales, mayormente archivados (2021-2023) o premios sin deadline; fichas sin Amount/dates → nada que extraer sin fabricar. El path T4 cubre futuros.
- unitar (21 noclose): cursos reales y vigentes (ediciones 2026, Fall 2026); tienen fecha de inicio, no deadline. No aplica patrón de cierre; no se purgan.

## Log
- L1 (verbatim usuario): "Ahora dime como es el estado de las fuentes y qué podemos hacer para optimizarlas"
- L2 2026-10-18: basal medido en vivo (3068/49.6/24.9/16.0/56.2). Propuesta A+B aprobada ("A+B juntos"). Hallazgo: Source ya trackea consecutive_empty_runs → T1 sin escrituras.
- L3 2026-10-18 (T1): T2 scope = disable dane, idb, sicon, ascun (0 filas c/u). sloan-grants (0 ítems, filas sin muestrear) fuera de scope.
- L4 2026-10-18 (T2): deploy OK. Flags SQL en 0023 = falsos positivos (shape 0007/0022, bound params). main.py/admin.py findings pre-existentes sin tocar.
