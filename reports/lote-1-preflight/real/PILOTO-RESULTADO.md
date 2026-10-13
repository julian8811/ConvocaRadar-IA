# Piloto L3 — resultado lote 1 (issue #59)

Ejecutado 2026-10-12 20:54 UTC en sandbox local, comando exacto de `run_pilot.sh`
(verificado byte-a-byte contra `manifest.md` antes de ejecutar).
5 invocaciones secuenciales, 5 requests totales, elapsed pared 10s (techo 60s).
Cada evidencia: `requests_made=1`, `duration_ms` max 3111 (techo 15s).
Sin secretos en URLs ni cuerpos (grep token/secret/api-key/bearer/password: 0).
Evidencia cruda: `real/<source>.live-probe.json` (copia de `piloto-*/live-probe-plan.json`).

## Por fuente

| fuente | HTTP | títulos muestra | accionable / editorial / ambigua / empleo-otro | veredicto |
|--------|------|-----------------|------------------------------------------------|-----------|
| novo-nordisk-grants | 200 JSON 747KB | 10 (Start Package Grants, Project Grants Bioscience/NatSci, Postdoc Fellowships Plant/Industrial Biotech, Nexa call…) | 10 / 0 / 0 / 0 → precisión aparente 100% | **GO** — WP-JSON parseable, títulos 100% accionables. `needs_human_review=false` formato; nota: idioma EN/DA, foco salud/biotech |
| grants-gov-forecast | 200 HTML 27KB (esperado RSS/XML) | 1: "Your session will expire in 3 minutes." | muestra nula (página de gate de sesión, no contenido) | **BLOCKED** — `live_blocked`, `pending_manual_review=true`. Soft-block/WAF de sesión; STOP por plan, sin reintentos |
| minciencias | 200 HTML 54KB | 7: "Cabecera", "Usted está aquí", "Convocatorias Minciencias", "Páginas", … (solo chrome de navegación) | 0 / 0 / 0 / 0 + 7 chrome no-informativo → precisión 0% **con extractor insuficiente** | **HOLD** — `needs_human_review=true`. HTTP ok pero extractor solo capturó chrome; probable lista renderizada por JS o markup distinto. Requiere inspección manual o mejor extractor antes de escalar |
| ukri-opportunities | 200 HTML 105KB | 11: "Funding finder", "Funding opportunity list", "filter options", … (esqueleto UI, cero oportunidades individuales) | 0 / 0 / 0 / 0 + 11 chrome → precisión 0% **con extractor insuficiente** | **HOLD** — `needs_human_review=true`. Mismo patrón que minciencias; probable lista JS. No es prueba de ausencia de oportunidades |
| innpulsa | 200 JSON 87KB | 10 (IATF 16949 mipymes, TCR-2026 clúster, Centros Fortalecimiento Tumaco/Popayán/Piedecuesta, ZASCA Jóvenes Cali, LGBTIQ+, XISQUA cacao, Valledupar 2026…) | 10 / 0 / 0 / 0 → precisión aparente 100% | **GO** — API REST limpia, títulos 100% accionables en ES, misión directa CO. `needs_human_review=false` formato |

## Veredicto global del lote: NO-GO global, GO parcial (2/5)

- **Escalables ya (2):** `novo-nordisk-grants`, `innpulsa` — formato + pertinencia acreditados con títulos reales.
- **Bloqueada (1):** `grants-gov-forecast` — gate de sesión; solo continúa con acceso alternativo autorizado manualmente (fuera de este piloto; prohibidos reintentos agresivos).
- **En revisión (2):** `minciencias`, `ukri-opportunities` — HTTP 200 pero sin títulos reales; el extractor actual no sirve para esas páginas. Decidir: inspección manual del HTML guardado (bytes recibidos 54KB/105KB, cuerpo completo disponible vía re-probe con guardado) o extractor JS. No escalar con el extractor actual.
- **Criterio aplicado:** GO = HTTP 200 + formato esperado + ≥1 título accionable real. STOP/BLOCKED = WAF/gate/403/429. HOLD = HTTP ok pero muestra no-informativa (UNKNOWN antes que certificar).

## Pendientes (para el padre)

1. Decidir destino de `piloto-*/` (artefacto crudo del comando exacto) vs `real/` (evidencia curada): ¿se commitean ambos o solo `real/` + este informe?
2. `grants-gov-forecast`: autorizar o no vía alternativa (nuevo preflight, no reintento ciego).
3. `minciencias` / `ukri-opportunities`: inspección manual o mejora de `extract_titles` para esas páginas.
4. Actualizar `manifest.json` (`muestra_titulos`, `needs_human_review`) — lo dejo al padre por ser cambio de diseño, no evidencia.
