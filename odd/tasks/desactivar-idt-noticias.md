# Desactivar idt-noticias (sólo-convocatorias) — deploy a producción

Objetivo: sacar las noticias del IDT del informe de turismo. Rama: main → cherry a server → rebuild api → reseed → purga. Runner: pytest (api), ruff.

## Specs

- **S1** — La sección turismo del informe no muestra noticias: la fuente `idt-noticias` queda deshabilitada en `seed.py` (dictamen E13, acuerdo sólo-convocatorias 2026-10-15). IDT sigue cubierto por `idt-experiencias-2026`.
- **S2** — Las 45 filas de noticias del IDT ya guardadas se purgan del servidor con respaldo JSON previo en `reports/`; la fila Source se conserva deshabilitada.
- **S3** — Los 9 `test_catalog_fully_enabled` (rojos en baseline por 5 deshabilitadas preexistentes de la tanda 041) esperan el conjunto verdadero de 6; pin nuevo `test_idt_noticias_disabled_newsroom_policy`.
- **S4** — Circuito producción: commit + push a main, cherry al branch del servidor, rebuild api, reseed, verify (enabled=false, 0 filas), purga.
- **S5** — Las 9 noticias de turismo de otras 5 fuentes legítimas (procolombia, bogota-d.e., bogota-cultura, cundinamarca, uniandes) se purgan por ID exacto con respaldo; las fuentes NO se deshabilitan (son convocatorias reales). Quedan fuera a propósito: anuncios de llamadas aunque pobres (premios 2024, cortometrajes, inscripción guianza, MinCIT sin fecha) y el evento ambiguo del Foro. Sin ban por URL: rompería fixtures legítimos (032 medellín sala-de-prensa, 034 PICTE /noticias/); el gate por evidencia queda como trabajo futuro.

## Tasks

- [x] **T1** (inline) — S1,S3: flag `enabled: False` en seed + excepción documentada en 9 tests + pin nuevo. RED observado → GREEN 49 passed. Commit: pendiente (va en T3).
- [x] **T2** (inline) — S2: `scripts/purge_idt_noticias.py` (dry-run default, `--apply` respalda y purga + dependientes). Compila; dry-run contra DB real pendiente (sin env local).
- [x] **T3** (inline) — S4: commit `87a71bb` + push a main (origin/main == 87a71bb). ✅ 2026-10-15
- [x] **T4** (inline) — S4: cherry-pick limpio al branch del servidor → commit `10d7724`; rebuild api (healthy). Worker sin cambios, no reiniciado. ✅ 2026-10-15
- [x] **T5** (inline) — S4: reseed con force=true (el seed sin force sólo adopta huérfanas: 203 skipped). Resultado: 203 updated, `idt-noticias.enabled=false`. ✅ 2026-10-15
- [x] **T6** (inline) — S4: purga prod `--apply`: backup `reports/purge-idt-noticias-20261015-041304.json` (45 filas, JSON validado) + 45 borradas; verify: enabled=false, remaining=0, contenedores healthy. ✅ 2026-10-15
- [x] **T7** (inline) — S5: `scripts/purge_turismo_news_20261015.py` (9 IDs exactos, backup, dry-run default) + commit `3069f04` + push + cherry `86805da` a servidor (sin rebuild: sin cambios en código api). ✅ 2026-10-15
- [x] **T8** (inline) — S5: purga prod de las 9 noticias (backup `reports/purge-turismo-news-20261015-041947.json` validado) + verify: turismo 26→17, 0 noticias. ✅ 2026-10-15

## Log

- **L1** (pedido original, verbatim): "Ahora requiero que pongas especial atención en las convocatorias que reportas, por ejemplo en la sesión de turismo estás reportando noticias y ya habiamos quedado que sólo se reportan convocatorias, analiza esto y trabaja con odd para corregir esto"
- Análisis: `idt-noticias` raspa `idt.gov.co/noticias` (categoría turismo); el fixture de `test_038_batch_parse.py` lo prueba con titulares de farándula urbana. Forense E13 ya lo había dictaminado. `segib-noticias` no toca turismo (categoría cooperación).
- Decisión usuario: desactivar + purgar lo guardado (no sólo desactivar).
- Subagentes negados por el runtime (explore y general: permission.rejected); usuario autorizó inline explícito.
- Hallazgo: 9 `test_catalog_fully_enabled` ya rojos en baseline por las 5 deshabilitadas de la tanda 041 (gate X3, issue #62); se sinceraron al conjunto de 6.
- Servidor verificado solo-lectura: branch `server/observatorio-production-prebasepath-20260909` en `6e3b325`, worktree limpio, `idt-noticias.enabled=true`, 45 filas de noticias. Alineación: local==origin/main (`d76c0ef`); servidor va por cherrys.
- Acceso servidor: SSH ubuntu@10.3.1.128:22 (credencial provista por el usuario en chat; no persistida; rotar sugerido).
- Circuito autorizado por el usuario ("dale"): commit → cherry → deploy → reseed → purga.
