# Auditoría de budget — lote 1 preflight (issue #59)

Verificación completa con 0 red: los 5 dry-runs existen y cada uno estima
exactamente 1 request; el piloto planea 5 GET secuenciales (1/fuente).

| fuente | plan | requests estimadas | hosts | network_used |
|--------|------|--------------------|-------|--------------|
| novo-nordisk-grants | dry-runs/novo-nordisk-grants.plan.json | 1 | novonordiskfonden.dk | false |
| grants-gov-forecast | dry-runs/grants-gov-forecast.plan.json | 1 | www.grants.gov | false |
| minciencias | dry-runs/minciencias.plan.json | 1 | minciencias.gov.co | false |
| ukri-opportunities | dry-runs/ukri-opportunities.plan.json | 1 | ukri.org | false |
| innpulsa | dry-runs/innpulsa.plan.json | 1 | convocatorias.innpulsacolombia.com | false |
| **TOTAL** | | **5** | 5 distintos | **false** |

Techos impuestos por código (`PROBE_BUDGET_DEFAULTS` + CLI `max_requests=1`):

- max_requests_per_source: 1 (CLI piloto) ≤ 10 (techo global)
- timeout por solicitud: ≤15s; deadline extremo a extremo: ≤60s
- tope 2MB/página con aborto de stream ANTES de completar (`BodyTooLargeError`)
- redirects: solo mismo host autorizado, máx 3; a otro host => `blocked_by_policy`
- concurrencia del piloto: 1 (bucle secuencial, sin paralelismo)
- 429 + Retry-After => transitorio (nunca muerta); WAF/403 => STOP + revisión
- URLs con credenciales / HTTP plano / puerto no-443 => `blocked_by_policy`, 0 red

Resultado: presupuesto CUMPLIDO (5 planeadas ≤ 5 permitidas, 0 ejecutadas).
