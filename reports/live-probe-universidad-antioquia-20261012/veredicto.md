# Probe real universidad-antioquia — veredicto resto (2026-10-12)

Rama: `fase4-probe-real-20261012`.

## Comandos (worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key universidad-antioquia --output reports/live-probe-universidad-antioquia-20261012` + plan con URL explícita → `live-probe-plan.json`.
2. Probe real (2 request(s), techo 3): `run_live_probe(allow_network=True, authorized_hosts=[apex+www del mismo sitio], resolve=guardia-DNS)` + httpx (timeout 15 s, sin seguir redirects cross-host), script efímero en `/tmp`, tandas de 20 con pausa de 30 s y jitter 2–4 s.
3. Extracción (1 request adicional, salvo bloqueo/nota POST): GET directo + parse liviano stdlib con autodetección (json/rss/sitemap/html/pdf), sin persistencia.

## Requests reales: 3 (techo 10)
- Probe: `live_ok` HTTP 200, 397 ms, 2 request(s).
- Extracción: html HTTP 302 text/html; charset=iso-8859-1, 248 B, 1 ítems → muestra de 1 títulos.
- Sin reintentos ante 403/429 (STOP por fuente); secuencial con jitter.

## Clasificación
- conectividad PASS probe (HTTP 200, 397 ms). Extracción PARCIAL (html: 1 ítems, muestra sin léxico claro de convocatoria) — posible JS/app shell o selectores insuficientes. NEEDS HUMAN REVIEW.

## Veredicto: CONTINUAR con pending_manual_review en pertinencia

## Archivos
- `live-probe-plan.json` · `live-probe-real.json` · `live-probe-extraccion.json` · `veredicto.md`
