# Dedup NIH + nav-junk Brasil + enriquecer flacas

Objetivo: (1) cerrar la ingesta duplicada NIH y purgar duplicados + basura
de navegación; (2) enriquecer las 1.531 flacas con fechas/montos. Runner:
pytest (api), ruff.

## Specs

- **S1** — `grants-gov-rss` deshabilitada (449 found/0 created en 30d; sus 24 filas existen duplicadas en grants-gov/simpler). Pin + catálogo 8→9.
- **S2** — Guardia `is_noise_title` contra labels de navegación ("Acesso à Informação", "Ações e Programas") + purga de las 5 filas BR por título exacto.
- **S3** — Backfill de fechas/montos sobre flacas con `scripts/backfill_llm_extraction.py` en tandas (dry-run primero); recontar thin al final.
- **S4** — Circuito: commit + push + cherry + rebuild + reseed + purge + verify.

## Tasks

- [ ] **T1** (inline) — S1: flag + pin + catálogo + script purga. RED→GREEN.
- [ ] **T2** (inline) — S2: guard + tests + purga BR.
- [ ] **T3** (inline) — S3: backfill en prod por tandas + recount. Lanzado detached (`--limit 1500`, log `/tmp/backfill.log` en servidor). 1510 flacas pendientes al lanzar. Progreso por poll.
- [ ] **T4** (inline) — S4: circuito completo.

## Log

- **L1** (pedido, verbatim): tanda elegida "Dedup NIH + Brasil, Enriquecer flacas"
- grants-gov-rss: 449/0 en 30d, 24/24 filas duplicadas en otras fuentes. simpler-grants (50) y grants-gov (49) quedan.
- backfill_llm_extraction.py ya existe (gap-fill, dry-run, --limit, --source-key): no hace falta código nuevo para S3.
