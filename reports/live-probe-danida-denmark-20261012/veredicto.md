# Probe real danida-denmark — veredicto resto (2026-10-12)

Rama: `fase4-probe-real-20261012`.

## Comandos (worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key danida-denmark --output reports/live-probe-danida-denmark-20261012` + plan con URL explícita → `live-probe-plan.json`.
2. Probe real (1 request(s), techo 3): `run_live_probe(allow_network=True, authorized_hosts=[apex+www del mismo sitio], resolve=guardia-DNS)` + httpx (timeout 15 s, sin seguir redirects cross-host), script efímero en `/tmp`, tandas de 20 con pausa de 30 s y jitter 2–4 s.
3. Extracción (1 request adicional, salvo bloqueo/nota POST): GET directo + parse liviano stdlib con autodetección (json/rss/sitemap/html/pdf), sin persistencia.

## Requests reales: 2 (techo 10)
- Probe: `live_ok` HTTP 200, 1037 ms, 1 request(s).
- Extracción: html HTTP 200 text/html; charset=utf-8, 52796 B, 4 ítems → muestra de 3 títulos.
- Sin reintentos ante 403/429 (STOP por fuente); secuencial con jitter.

## Clasificación
- conectividad PASS (`live_ok`, HTTP 200, 501 ms, 52796 B). Extracción PASS (html: 4 ítems → 3 títulos, 3 con léxico de convocatoria). Pertinencia PASS por muestra. Sin review.

## Veredicto: CONTINUAR

## Archivos
- `live-probe-plan.json` · `live-probe-real.json` · `live-probe-extraccion.json` · `veredicto.md`
