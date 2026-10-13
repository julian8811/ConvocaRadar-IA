# Probe real nsf-funding-rss — veredicto lote 5 (2026-10-12)

Rama: `fase4-probe-real-20261012`.

## Comandos (worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key nsf-funding-rss --output reports/live-probe-nsf-funding-rss-20261012` + plan con URLs explícitas → `live-probe-plan.json`.
2. Probe real (1 request): `run_live_probe(allow_network=True, max_requests=1, authorized_hosts=[host], resolve=guardia-DNS)` + httpx dedicado (timeout 15 s, sin seguir redirects), script efímero en `/tmp`.
3. Extracción (1 request adicional): GET/POST directo + parse liviano stdlib (títulos), sin persistencia.

## Requests reales: 2 (techo 10; sin anomalías → sin STOP)
- Probe: `live_ok` HTTP 200, 244 ms.
- Extracción: HTTP 200 application/rss+xml; charset=utf-8, 13127 B, 15 ítems → muestra de 5 títulos.
- Sin 403/WAF, sin 429, sin redirects cross-host, sin DNS privado.

## Clasificación
- conectividad PASS (live_ok, 200, 244ms). Extracción PASS (15 ítems RSS → títulos de programas). Pertinencia PASS: programas de funding reales (GRFP, Expeditions, EFRI). Sin review.

## Veredicto: CONTINUAR

## Archivos
- `live-probe-plan.json` (dry-run) · `live-probe-real.json` (outcome + evidencia) · `live-probe-extraccion.json` (muestra de títulos) · `veredicto.md`
