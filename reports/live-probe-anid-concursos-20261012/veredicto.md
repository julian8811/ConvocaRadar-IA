# Probe real anid-concursos — veredicto lote 20 (2026-10-12)

Rama: `fase4-probe-real-20261012`.

## Comandos (worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key anid-concursos --output reports/live-probe-anid-concursos-20261012` + plan con URL explícita → `live-probe-plan.json`.
2. Probe real (1 request): `run_live_probe(allow_network=True, max_requests=1, authorized_hosts=[host], resolve=guardia-DNS)` + httpx (timeout 15 s, sin redirects), script efímero en `/tmp`.
3. Extracción (1 request adicional, salvo bloqueo): GET directo + parse liviano stdlib, sin persistencia.

## Requests reales: 1 (techo 10)
- Probe: `live_blocked` HTTP 403, 104 ms.
- Extracción: HTTP 403 text/html, 919 B, 0 ítems → muestra de 0 títulos.
- Sin reintentos ante 403/429 (STOP por fuente); jitter 2–4 s entre fuentes; secuencial.

## Clasificación
- conectividad BLOCKED (403, 104ms) → live_blocked con pending_manual_review. STOP por fuente aplicado, sin retry. Causa probable: WAF/bloqueo geográfico o bot-check. Registrar y seguir con resto del catálogo.

## Veredicto: BLOQUEADA — no reintentar

## Archivos
- `live-probe-plan.json` · `live-probe-real.json` · `live-probe-extraccion.json` · `veredicto.md`
