# Piloto real ASCUN — veredicto lote 0 (2026-10-12)

Fuente: `ascun-convocatorias` · Rama: `fase4-probe-real-20261012` · Sin commits.

## Comandos ejecutados (todo en el worktree, PYTHONPATH=apps/api)
1. Dry-run (0 red): `python -m app.audit.cli --mode live-probe --dry-run --source-key ascun-convocatorias --output reports/live-probe-ascun-20261012` → plan vigente: 1 request, host `ascun.org.co`, budgets ≤10 req / ≤15 s c/u / ≤60 s total.
2. NOTA: el CLI con `--allow-network` usa `transport=None` y se niega por diseño (`refused_missing_flags`, 0 red). El request real se ejecutó con `run_live_probe(allow_network=True, max_requests=1, authorized_hosts=["ascun.org.co"], resolve=guardia-DNS)` + transporte httpx dedicado (timeout 15 s, sin seguir redirects), script efímero en `/tmp` (fuera del repo).
3. Extracción (1 request adicional, mismo URL): parse con `AscunConnector.parse`, sin persistencia.

## Requests reales totales: 2 (lejos del techo de 10; 0 anomalías → sin STOP)
| # | URL | HTTP | Latencia | Resultado |
|---|-----|------|----------|-----------|
| 1 | `GET ascun.org.co/wp-json/wp/v2/posts?search=convocatoria…` | 200 JSON | 3131 ms | `live_ok`, TTL 24 h, sin truncado, sin review |
| 2 | mismo URL (extracción) | 200 JSON 173 677 B | 909 ms | 20 ítems JSON → 20 candidatos, 20/20 con URL `ascun.org.co` |

Sin 403/WAF, sin 429, sin redirects, sin DNS privado. Resguardos SSRF/DNS activos en ambos.

## Clasificación por dimensión
- **conectividad: PASS (live_ok)** — 200 real, latencia 0.9–3.1 s (holgura 5–16× bajo 15 s/20 s del conector).
- **extracción: PASS técnico** — 20/20 ítems parsean a candidatos válidos (título + URL ASCUN).
- **pertinencia: NEEDS HUMAN REVIEW** — la muestra trae mayormente *noticias sobre* convocatorias (encuentros, lanzamientos, cifras SNIES), no convocatorias accionables. El `search=convocatoria` del WP devuelve ruido editorial. No bloquea el piloto, pero el lote 0 debe registrar `needs_human_review` en pertinencia antes de escalar.
- Resto de dimensiones: sin cambios (históricas, fuera del alcance del piloto).

## Veredicto: CONTINUAR A 5 (condicional)
Lote 0 válido para escalar a 5 fuentes **con la condición** de arrastrar el hallazgo de pertinencia: cualquier fuente WP-`search=` debe evaluarse también por pertinencia (muestra de títulos), no solo por 200 + parse. Sin esa guarda, escalar replica ruido.
Criterio STOP aplicado y no disparado: 0× 403/WAF, 0× 429, 0 redirects cross-host, 2/10 requests.

## Archivos generados (solo nuevos, bajo `reports/live-probe-ascun-20261012/`)
- `live-probe-plan.json` (dry-run, ya existía del preflight — reutilizado)
- `live-probe-real.json` (outcome `live_ok` + evidencia sanitizada)
- `live-probe-extraccion.json` (20 ítems → 20 candidatos + muestra)
- `veredicto.md` (este archivo)

## Commits: ninguno (sin bug que amerite fix).
## Pendientes
- Registrar `needs_human_review` en pertinencia para `ascun-convocatorias` al certificar el lote 0.
- Para el escalado a 5: exigir muestra de extracción (títulos) por fuente, no solo status/parse-counts.
- Considerar `reportar` (no reintentar): latencia WP variable 0.9–3.1 s; el bound de 20 s del conector sigue sano.
