# Probe real conacyt-mexico — veredicto resto (2026-10-12)

Rama: `fase4-probe-real-20261012`.

## Comandos (worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key conacyt-mexico --output reports/live-probe-conacyt-mexico-20261012` + plan con URL explícita → `live-probe-plan.json`.
2. Probe real (1 request(s), techo 3): `run_live_probe(allow_network=True, authorized_hosts=[apex+www del mismo sitio], resolve=guardia-DNS)` + httpx (timeout 15 s, sin seguir redirects cross-host), script efímero en `/tmp`, tandas de 20 con pausa de 30 s y jitter 2–4 s.
3. Extracción (1 request adicional, salvo bloqueo/nota POST): GET directo + parse liviano stdlib con autodetección (json/rss/sitemap/html/pdf), sin persistencia.

## Requests reales: 1 (techo 10)
- Probe: `blocked_by_policy` HTTP None, 0 ms, 1 request(s).
- Extracción: no ejecutada (bloqueo (sin extracción)).
- Sin reintentos ante 403/429 (STOP por fuente); secuencial con jitter.

## Clasificación
- conectividad BLOCKED (`blocked_by_policy`, HTTP None, 0 ms) → pending_manual_review. STOP por fuente aplicado, sin retry. Registrar causa y seguir con resto del catálogo.

## Veredicto: BLOQUEADA — no reintentar

## Archivos
- `live-probe-plan.json` · `live-probe-real.json` · `live-probe-extraccion.json` · `veredicto.md`
