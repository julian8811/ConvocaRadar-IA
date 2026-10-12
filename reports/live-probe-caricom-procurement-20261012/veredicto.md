# Probe real caricom-procurement — veredicto lote 20 (2026-10-12)

Rama: `fase4-probe-real-20261012`.

## Comandos (worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key caricom-procurement --output reports/live-probe-caricom-procurement-20261012` + plan con URL explícita → `live-probe-plan.json`.
2. Probe real (1 request): `run_live_probe(allow_network=True, max_requests=1, authorized_hosts=[host], resolve=guardia-DNS)` + httpx (timeout 15 s, sin redirects), script efímero en `/tmp`.
3. Extracción (1 request adicional, salvo bloqueo): GET directo + parse liviano stdlib, sin persistencia.

## Requests reales: 2 (techo 10)
- Probe: `live_ok` HTTP 200, 750 ms.
- Extracción: HTTP 200 text/html; charset=UTF-8, 141607 B, 4 ítems → muestra de 5 títulos.
- Sin reintentos ante 403/429 (STOP por fuente); jitter 2–4 s entre fuentes; secuencial.

## Clasificación
- conectividad PASS (200, 750ms). Extracción PARCIAL: headings genéricos ('Tenders', oficinas). Listado de tenders requiere selectores. NEEDS HUMAN REVIEW.

## Veredicto: CONTINUAR con pending_manual_review en pertinencia

## Archivos
- `live-probe-plan.json` · `live-probe-real.json` · `live-probe-extraccion.json` · `veredicto.md`
