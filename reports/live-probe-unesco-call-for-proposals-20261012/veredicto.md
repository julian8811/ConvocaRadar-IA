# Probe real unesco-call-for-proposals — veredicto lote 5 (2026-10-12)

Rama: `fase4-probe-real-20261012`.

## Comandos (worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key unesco-call-for-proposals --output reports/live-probe-unesco-call-for-proposals-20261012` + plan con URLs explícitas → `live-probe-plan.json`.
2. Probe real (1 request): `run_live_probe(allow_network=True, max_requests=1, authorized_hosts=[host], resolve=guardia-DNS)` + httpx dedicado (timeout 15 s, sin seguir redirects), script efímero en `/tmp`.
3. Extracción (1 request adicional): GET/POST directo + parse liviano stdlib (títulos), sin persistencia.

## Requests reales: 2 (techo 10; sin anomalías → sin STOP)
- Probe: `live_ok` HTTP 200, 1010 ms.
- Extracción: HTTP 200 text/html; charset=utf-8, 74038 B, 6 ítems → muestra de 5 títulos.
- Sin 403/WAF, sin 429, sin redirects cross-host, sin DNS privado.

## Clasificación
- conectividad PASS (live_ok, 200, ~1s). Extracción PARCIAL: página HTML genérica con 6 headings pero mezcla contenido editorial ('Share', nav). Pertinencia NEEDS HUMAN REVIEW: requiere conector con selectores para aislar calls reales. Clasificación + pending_manual_review.

## Veredicto: CONTINUAR con pending_manual_review en pertinencia

## Archivos
- `live-probe-plan.json` (dry-run) · `live-probe-real.json` (outcome + evidencia) · `live-probe-extraccion.json` (muestra de títulos) · `veredicto.md`
