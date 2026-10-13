# Probe real horizon-europe-sedia — veredicto resto (2026-10-12)

Rama: `fase4-probe-real-20261012`.

## Comandos (worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key horizon-europe-sedia --output reports/live-probe-horizon-europe-sedia-20261012` + plan con URL explícita → `live-probe-plan.json`.
2. Probe real (1 request(s), techo 1): `run_live_probe(allow_network=True, authorized_hosts=[apex+www del mismo sitio], resolve=guardia-DNS)` + httpx (timeout 15 s, sin seguir redirects cross-host), script efímero en `/tmp`, tandas de 20 con pausa de 30 s y jitter 2–4 s.
3. Extracción (1 request adicional, salvo bloqueo/nota POST): GET directo + parse liviano stdlib con autodetección (json/rss/sitemap/html/pdf), sin persistencia.

## Requests reales: 1 (techo 10)
- Probe: `live_transient` HTTP 405, 583 ms, 1 request(s).
- Extracción: no ejecutada (nota: el conector usa POST; probe GET solo conectividad).
- Sin reintentos ante 403/429 (STOP por fuente); secuencial con jitter.

## Clasificación
- conectividad TRANSIENT (HTTP 405, err=None) → no confundir con muerta; revalidar en 15 min (TTL corto).

## Veredicto: TRANSITORIA — reintento futuro, pending_manual_review

## Archivos
- `live-probe-plan.json` · `live-probe-real.json` · `live-probe-extraccion.json` · `veredicto.md`
