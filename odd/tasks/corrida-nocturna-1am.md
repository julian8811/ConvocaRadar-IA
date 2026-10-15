# Corrida nocturna 1 AM COT — barrido forzado diario

Objetivo: corrida completa forzada a la 01:00 America/Bogota todos los días.
Corre solo en el worker (`SCHEDULER_ENABLED=true`; api lo tiene en false).
Runner: pytest (api), ruff.

## Specs

- **S1** — Settings nuevos: `nightly_sweep_enabled=true`, `nightly_sweep_hour=1`, `nightly_sweep_tz="America/Bogota"` (con override por env).
- **S2** — El loop del scheduler fuerza todas las habilitadas en el primer tick ≥01:00 COT una vez por día (guardia en memoria por fecha + log `nightly_sweep_start`).
- **S3** — Helper puro `_nightly_force_due()` testeado: bordes 00:59/01:00, mismo día, día siguiente, disabled.
- **S4** — Circuito: commit + push + cherry + rebuild **worker** + verify (config + helper + worker healthy). La prueba viva es el log de la 01:00.

## Tasks

- [ ] **T1** (inline) — S1,S2,S3: settings + trigger + tests. RED→GREEN.
- [ ] **T2** (inline) — S4: deploy worker + verify.

## Log

- **L1** (pedido original, verbatim): "programa la corrida en horas de la madrugada a la 1 de la mañana hora colombia"
- Arquitectura verificada: un solo scheduler (worker, `python -m app.worker`); api con scheduler en false. Guardia en memoria alcanza; un restart edge duplica como mucho una pasada (con log).
- Colombia UTC-5 sin DST: offset estable, `zoneinfo` disponible.
