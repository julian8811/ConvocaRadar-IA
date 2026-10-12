# Probe real unicef-venture-fund — veredicto lote 20 (2026-10-12)

Rama: `fase4-probe-real-20261012`.

## Comandos (worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key unicef-venture-fund --output reports/live-probe-unicef-venture-fund-20261012` + plan con URL explícita → `live-probe-plan.json`.
2. Probe real (1 request): `run_live_probe(allow_network=True, max_requests=1, authorized_hosts=[host], resolve=guardia-DNS)` + httpx (timeout 15 s, sin redirects), script efímero en `/tmp`.
3. Extracción (1 request adicional, salvo bloqueo): GET directo + parse liviano stdlib, sin persistencia.

## Requests reales: 2 (techo 10)
- Probe: `live_ok` HTTP 200, 299 ms.
- Extracción: HTTP 200 text/html; charset=UTF-8, 176088 B, 7 ítems → muestra de 5 títulos.
- Sin reintentos ante 403/429 (STOP por fuente); jitter 2–4 s entre fuentes; secuencial.

## Clasificación
- conectividad PASS (200, 299ms). Extracción PASS: títulos de calls reales ('Call for Blockchain Ventures', 'Closed Calls'). Pertinencia PASS. Sin review.

## Veredicto: CONTINUAR

## Archivos
- `live-probe-plan.json` · `live-probe-real.json` · `live-probe-extraccion.json` · `veredicto.md`
