# Probe real idrd-convocatorias — veredicto fuentes faltantes (2026-10-12)

Rama: `fase4-probe-real-20261012`.

## Comandos (worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key idrd-convocatorias --output reports/live-probe-idrd-convocatorias-20261012` + plan con URL explícita → `live-probe-plan.json`.
2. Probe real (1 request): `run_live_probe(allow_network=True, max_requests=1, authorized_hosts=[host], resolve=guardia-DNS)` + httpx (timeout 15 s, sin redirects), script efímero en `/tmp`.
3. Extracción (1 request adicional): GET directo + parse liviano stdlib, sin persistencia.

## Requests reales: 2 (techo 10)
- Probe: `live_ok` HTTP 200, 367 ms.
- Extracción: HTTP 200 text/html; charset=UTF-8, 97509 B, 129 ítems → muestra de 5 títulos.
- Sin reintentos ante 403/429 (STOP por fuente); jitter 2–4 s entre fuentes; secuencial.

## Clasificación
- conectividad PASS (200, 367ms). Extracción OK: 129 enlaces (mayoría navegación institucional + documentos; el detalle de avisos contractuales requiere parse específico del conector).

## Veredicto: CONTINUAR (live_ok, sin pending_manual_review)

## Archivos
- `live-probe-plan.json` · `live-probe-real.json` · `live-probe-extraccion.json` · `veredicto.md`
