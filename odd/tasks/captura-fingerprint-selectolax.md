# Captura: pin selectolax + skip-enrich por DOM sin cambios

Objetivo: (1) blindar el backend HTML contra majors futuros; (2) no pagar
LLM-enrichment cuando la página no cambió. Runner: pytest (api), ruff.

## Specs

- **S1** — `selectolax>=1.0,<2` en requirements + pyproject (prod corre 1.0.0 con lexbor OK; el error Modest del 9-oct era imagen anterior a la migración 9e0aecb). Pin de regresión: ningún import fuera de `selectolax.lexbor`.
- **S2** — En `run_source_inline`, si el DOM hash no cambió desde el scrape anterior, se salta `_batch_enrich` (y su fallback serial): mismo contenido ⇒ misma extracción. El parse/validate/persist corren igual (barato y a prueba de puntos ciegos de la normalización). Log + stat `enrich_skipped_unchanged`.
- **S3** — Circuito: commit + push + cherry + rebuild api+worker + verify (nuevo run registra skips).

## Tasks

- [x] **T1** (inline) — S1: pin `selectolax>=1.0,<2` + test regresión + env local a 1.0.0. ✅ 2026-10-15
- [x] **T2** (inline) — S2: hash compuesto + skip pre-parse + finalize success. RED→GREEN, 100 passed. ✅ 2026-10-15
- [x] **T3** (inline) — S3: deploy api+worker (cherrys 77e5a84, a895f76) + prueba viva: sdde 22.6s→1.0s con `dom_unchanged_skip`. ✅ 2026-10-15

## Log

- **L1** (pedido original, verbatim): "implementa" (sobre recomendación 1+5: fingerprint + selectolax)
- selectolax: todo el código usa lexbor; el error Modest del 9-oct vino de imagen anterior a 9e0aecb (commit 10:52, run fallido 13:07 con imagen vieja). Sin recurrencias desde entonces.
- dom_hash ya existe por fuente (Change D) pero solo observa; este trabajo lo vuelve decisión de skip solo para enrich (lo caro), no para parse/persist.
