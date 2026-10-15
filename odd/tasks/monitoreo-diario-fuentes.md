# Monitoreo diario total — todas las fuentes a daily

Objetivo: barrido diario de las 203 habilitadas (usuario: monitoreo diario de
todas, sin recortes de frecuencia). Runner: pytest (api), ruff.

## Specs

- **S1** — Toda fuente habilitada en `seed.py` queda con `scraping_frequency: "daily"`.
- **S2** — Los tests de batch que pinean `"weekly"`/`"monthly"` se actualizan a `"daily"` con razón documentada.
- **S3** — El sweep diario completo se verifica viable (hard budget 360s + conc 5 ya deployados); verify en prod: sweep completo <60 min.
- **S4** — Circuito producción: commit + push main, cherry a servidor, rebuild api, reseed, verify.

## Tasks

- [x] **T1** (inline) — S1,S2: flip de 130 frecuencias a daily (solo habilitadas; deshabilitadas intactas por gates) + pin `test_seed_daily_cadence.py` + 039/040 a daily. RED→GREEN, 111 passed. ✅ 2026-10-15
- [ ] **T2** (inline) — S3,S4: commit + push + cherry + rebuild + reseed + verify sweep.

## Log

- **L1** (pedido original, verbatim): "requiero que realices un analisis exhaustivo de las fuentes, necesitamos optimizar la captura de la información"
- Análisis previo: 12+ diarias con 0 creadas/30d pero miles encontradas (dedup absorbe); zombies con runs en cero; backoff muerto; duplicación NIH/Brasil.
- Decisión usuario: NADA de recortes — monitoreo diario de todas las fuentes (rechazó weekly, eligió solo "Todo daily", sin digest).
- Riesgo anotado: sitios lentos/gobiernos pueden rate-limitear con cadencia diaria; el jitter por fuente y el hard budget mitigan; vigilar health post-cambio.
