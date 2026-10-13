# Probe real idartes-pde-portafolio-2026 — veredicto resto (2026-10-12)

Rama: `fase4-probe-real-20261012`.

## Comandos (worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key idartes-pde-portafolio-2026 --output reports/live-probe-idartes-pde-portafolio-2026-20261012` + plan con URL explícita → `live-probe-plan.json`.
2. Probe real (1 request(s), techo 3): `run_live_probe(allow_network=True, authorized_hosts=[apex+www del mismo sitio], resolve=guardia-DNS)` + httpx (timeout 15 s, sin seguir redirects cross-host), script efímero en `/tmp`, tandas de 20 con pausa de 30 s y jitter 2–4 s.
3. Extracción (1 request adicional, salvo bloqueo/nota POST): GET directo + parse liviano stdlib con autodetección (json/rss/sitemap/html/pdf), sin persistencia.

## Requests reales: 2 (techo 10)
- Probe: `live_ok` HTTP 200, 13925 ms, 1 request(s).
- Extracción: html HTTP 200 text/html; charset=UTF-8, 76236 B, 6 ítems → muestra de 5 títulos.
- Sin reintentos ante 403/429 (STOP por fuente); secuencial con jitter.

## Clasificación
- conectividad PASS (`live_ok`, HTTP 200, 13201 ms, 76236 B). Extracción PASS (html: 6 ítems → 5 títulos, 3 con léxico de convocatoria). Pertinencia PASS por muestra. Sin review.

## Veredicto: CONTINUAR

## Archivos
- `live-probe-plan.json` · `live-probe-real.json` · `live-probe-extraccion.json` · `veredicto.md`
