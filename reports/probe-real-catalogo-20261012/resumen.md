# Probe real catálogo completo — resumen (2026-10-12)

Rama: `fase4-probe-real-20261012`. Catálogo: 201 fuentes (seed.py). Probadas con red real: 198. Excluidas preventivamente (WAF conocido, sin tocar): `sloan-grants`, `camara-comercio-bogota`, `developmentaid-tenders`.

## Totales globales (198 probadas)

- `live_ok` (200 con cuerpo): **155** = lote0 1 (ascun) + lote5 5 + lote20 19 + resto 130
- `live_dead` (404/410): **16** → anp-brasil, camara-comercio-cali, camara-comercio-medellin, cepal-convocatorias, finagro-lec-2026, flacso-convocatorias, giz-alemania, global-environment-facility, green-climate-fund, inct-brasil, oei-convocatorias, procolombia-inversion, rutann-convocatorias, sgc-convocatorias, supersolidaria-convocatorias, universidad-nacional-colombia
- `live_blocked` (403/WAF): **4** → anid-concursos (lote 20) + eurimages-council-europe, fondecyt-chile, interamerican-foundation
- `blocked_by_policy` (redirect cross-host / SSRF-guard): **15** → acumen-fellowship, camara-comercio-bquilla, colombia-productiva, conacyt-mexico, erasmus-plus-opportunities, eu-culture-moves-europe, iie-programs, mintic-convocatorias, mozilla-foundation, nz-manaaki-scholarships, procolombia-convocatorias, proinnovate-calendario, rhodes-scholarship, sena-convocatorias, uniandes-oportunidades-investigacion
- `live_transient` (405 POST-only / timeout / red): **8** → erc-calls, eu-creative-europe-calls, fontur-programas, gates-cambridge, horizon-europe-sedia, idartes-convocatorias, msca-funding, nrf-south-africa-bursaries
- `over_budget`: 0 (fix apex/www + budget 3 resolvió los 4 casos de tanda 0/1).

Requests: ~2 por fuente (probe + extracción), techo 10/fuente nunca superado (máx 4). Sin reintentos ante 403/429. Jitter 2–4 s, secuencial global, pausa 30 s entre tandas.

## Gates
- Lote 5: 5/5 live_ok, 0 bloqueos → VERDE.
- Lote 20: 19/20 live_ok + 1 bloqueo (anid 403) = 5% → VERDE.
- Resto tanda 1: frenada bruta 6/10 → diagnóstico: 4 artefactos metodológicos (www↔apex mismo sitio + budget 1) + 1 GET-vs-POST (usaid) → fix autorizado (apex/www mismo sitio, budget 3, POST donde el conector lo usa) → redo: 0 bloqueos adversos pendientes de artefacto. Bloqueos adversos reales totales del catálogo: 4×403 (anid, fondecyt-chile, interamerican-foundation, eurimages).
- Tandas 2–8: bloqueos brutos 5–17% por tanda, adversos ≤1 por tanda → VERDE.

## Hallazgos que requieren acción humana (pending_manual_review)
1. **Feeds grants.gov retirados**: `grants-gov-rss` y `grants-gov-forecast` devuelven 200 HTML (landing) con 0 ítems — confirmar nueva URL o dar de baja las fuentes RSS.
2. **Sitios mudados/fusionados** (redirect cross-host bloqueado por política): `procolombia-convocatorias`→Drive, `sena-convocatorias`→betowa.sena.edu.co, `colombia-productiva`→innpulsa, `conacyt-mexico`→?, `proinnovate-calendario`→? — actualizar `base_url` en catálogo.
3. **APIs POST-only**: `horizon-europe-sedia`, `erc-calls`, `msca-funding`, `eu-creative-europe-calls` (405 a GET) — el probe solo valida conectividad; la extracción debe ir por el conector.
4. **Pertinencia**: WP-`search=` (ascun) trae ruido editorial; ~54 fuentes HTML con extracción parcial (JS/app-shell: ukri, wellcome, idrc, undp, oas, caricom…) — exigen muestra de títulos, no solo 200 (condición lote 0 cumplida en este informe).
5. **Muertas (16)**: verificar y dar de baja o corregir URL (incl. rutann 404, unal 404, cámaras medellín/cali 404).
6. **403 reales (4)**: anid, fondecyt-chile, interamerican-foundation, eurimages — no reintentar sin cambio de estrategia; posible WAF/geo-bloqueo.

## Evidencia por fuente
`reports/live-probe-<key>-20261012/` con `live-probe-plan.json` (dry-run 0 red) + `live-probe-real.json` (outcome) + `live-probe-extraccion.json` (muestra de títulos) + `veredicto.md`.