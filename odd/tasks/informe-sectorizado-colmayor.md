# Informe sectorizado + línea Colmayor — feature ODD

## Objective
El informe de convocatorias clasifica cada oportunidad en un gran grupo (sector) vía LLM y presenta el informe agrupado por sector con la línea gráfica del Colegio Mayor (logo, favicon, colores/tipografía del membrete).

## Problem
El informe actual (`generate_report_html` en `apps/api/app/services/export.py:89`) agrupa por `categories` libres (ruido: cientos de categorías distintas, tres idiomas) y usa marca genérica teal (`_BRAND_*`, `export.py:72-86`). No hay sectorización estable ni identidad Colmayor.

## Why
Pedido explícito del usuario: sectorizar con LLM en grandes grupos + línea gráfica Colmayor (assets en `/mnt/d/Colmayor/Formatos Colmayor/`).

## Análisis de clasificadores (decisión)
Taxonomía propuesta (11): turismo, investigación, emprendimiento, innovación, transferencia tecnológica, educación, salud, ambiente, cultura, infraestructura, otros.

| Enfoque | Costo 3106 filas | Precisión | Latencia | Operabilidad |
|---|---|---|---|---|
| A. LLM puro (Groq, zero-shot) | ~3.7h + pacing (precedente E16) | Alta (ES/EN/PT) | Alta una vez (cache DB) | Simple; no-determinismo → requiere confianza + auditoría |
| B. Reglas determinísticas (keywords) | ~0 | Media (listas por sector/idioma a curar) | Instantánea | Explicable, frágil ante vocabulario nuevo |
| C. Embeddings (pgvector ya 100%) | ~0 (infra existe) | Media-alta con prototipos bien escritos | Baja | Requiere calibrar umbral + set de evaluación |
| **D. Híbrido (elegido)** | Bajo (LLM solo al resto) | Alta | Baja amortizada | Capas como `ai.py`: reglas → embeddings → LLM juez; todo cacheado con confianza + procedencia |

D gana: reglas gratis para lo obvio (ej. "turismo", "posdoctorado"), embeddings para lo medio, Groq solo para el resto; cada fila guarda `sector + sector_confidence + sector_source` (rules/embeddings/llm) y es re-auditable.

## Scope
- IN: taxonomía fija versionada; clasificador híbrido con cache en DB (migración: `sector`, `sector_confidence`, `sector_source`); script backfill por batches con pacing (precedente `scripts/backfill_*`); informe agrupado por sector (HTML+XLSX+PDF); línea Colmayor en `export.py` (colores/tipografía extraídos del membrete, logo redimensionado — los jpeg pesan 1.5MB y van a base64 en el HTML); tests TDD; deploy + verify en servidor.
- OUT: re-entrenar modelos; cambiar el pipeline de scraping; nuevos formatos de informe; favicon web del observatorio (solo informe, salvo que se pida).
- Assets: copiar a `apps/api/app/assets/brand/colmayor/` (logo + favicon redimensionados + tokens extraídos del `.docx`); los originales quedan fuera del repo.

## Constraints
- TDD strict (RED→GREEN) en clasificador y merge de informe.
- LLM solo donde aporta: reglas primero; Groq con pacing 15s y sleep (lección E16); gap-fill: nunca reclasificar un sector con confianza ≥ umbral salvo `--force`.
- Marca: nada de 1.5MB en base64 — redimensionar a ancho ≤800px al ingresar el asset; contraste accesible sobre fondos del membrete.
- Commits Conventional; deploy a servidor con cherry-pick solo-código + rebuild + verify (patrón E19–E24). Push/merge los decide el usuario.

## Tasks
- [x] **T1 (P1)** ✅ 2026-10-11 Taxonomía v1 (11 sectores, confirmada) + set de evaluación `apps/api/tests/fixtures/sectores_eval.json` (90 filas ES/EN/PT, pre-etiquetado LLM + sign-off usuario).
- [x] **T2 (P1 writer)** ✅ 2026-10-11 Clasificador por reglas ES/EN/PT (`app/core/sectors.py`) + 37 tests. Baseline honesto: accuracy 0.867 (pin 0.85). Flojos para T3: transferencia tecnológica, `otros`, educación.
- [x] **T3 (P1 writer)** ✅ 2026-10-11 Capa embeddings (prototipos + `classify_with_fallback` solo sobre reglas-`otros`). Resultado honesto: combinada 0.867 = baseline, sin regresión (pin 0.85). Rescate real queda para el juez LLM (12 otros + 8 confident-wrong). Spot-check padre 52 passed.
- [x] **T4 (P1 writer)** ✅ 2026-10-11 Juez LLM + migración 0017 + `scripts/backfill_sector.py` (dry-run default, pacing 3s, gap-fill). Accuracy 0.900 pineada (stub; Groq real pendiente T7). 76 passed + 23 triangulación; spot-check padre 76 passed.
- [x] **T5 (P1 writer)** ✅ 2026-10-11 Informe agrupado por sector (HTML secciones por taxonomía + XLSX con columna Sector + PDF por mismo pipeline). Compatibilidad byte-idéntica sin sectores. 7 passed + vecinas 19/210; spot-check padre 31 passed.
- [x] **T6 (P1)** ✅ 2026-10-11 Línea Colmayor (tokens extraídos de píxeles del escudo — el docx no trae tokens; assets 800px/64px <150KB; reemplazo directo en `export.py` con fallback). 16 passed + vecinas 217; spot-check padre 16 passed.
- 2026-10-11: T7 deployado (cherry `2c0439d`, migración 0017 OK, marca Colmayor verificada en PDF muestra) pero backfill ABORTADO limpio: `asyncio.run()` dentro del loop + falta `embed_fn`. DB intacta (0 con sector).
- [x] **T8 (P1 writer)** ✅ 2026-10-11 Juez async-safe (`agroq_sector_judge` + `aclassify_sector`, `to_thread` para embeddings) + `embed_fn`/`llm_client` en backfill. TDD RED con forma exacta del bug → GREEN 81 passed (29 sin RuntimeWarnings); spot-check padre 29 passed.
- [ ] **T7 (P1)** Deploy + verify en servidor (patrón E19–E24) + medición de cobertura de sectorización.

## Acceptance
- ≥90% del set T1 clasificado correctamente (end-to-end híbrido).
- 100% de oportunidades con sector o `otros` + confianza; re-corridas idempotentes.
- Informe de muestra agrupado por sector con marca Colmayor, verificado visualmente.
- Suite verde; sin regresiones en export existente.

## Progress
- 2026-10-11: doc creado (plan). Análisis de clasificadores → híbrido D. Taxonomía propuesta pendiente de sign-off (11 sectores). Mirror Engram pendiente.

## Next step
- Sign-off de taxonomía (o lista propia del usuario) → T1.
