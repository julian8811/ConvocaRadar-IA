# Lote 1 — preflight 5 fuentes (issue #59)

Preflight con **0 requests externas**. Gate: NO-GO para red hasta autorización
expresa posterior (L3, fuera de este encargo). `manifest.json` es la fuente
estructurada; este archivo es su lectura humana.

## Fuentes (5, hosts distintos, no-ASCUN, sin WAF conocido)

| # | source_key | tipo | host autorizado | justificación |
|---|------------|------|-----------------|---------------|
| 1 | `novo-nordisk-grants` | api (WP-JSON) | novonordiskfonden.dk | Fundación privada grande salud/biotech; único WP del lote |
| 2 | `grants-gov-forecast` | rss | www.grants.gov | Forecast federal EEUU; único RSS del lote |
| 3 | `minciencias` | html | minciencias.gov.co | Ente rector ciencia CO; alto impacto local |
| 4 | `ukri-opportunities` | html | ukri.org, www.ukri.org | Financiador público UK; alto impacto global |
| 5 | `innpulsa` | api | convocatorias.innpulsacolombia.com | API REST emprendimiento CO; único API puro |

Excluidos con WAF conocido (sin repetir host sin justificación escrita):
`sloan-*`, `camara-comercio-bogota` (akamai), `developmentaid-tenders`
(cloudflare). Ninguna fuente del lote comparte host.

## Presupuesto auditado

5 GET máximo (1/fuente), secuencial, timeout ≤15s c/u, deadline ≤60s total,
tope 2MB con aborto pre-recepción, redirects solo mismo host autorizado,
STOP + `pending_manual_review` ante WAF/403/429. Detalle: `budget-audit.md`.

## Pertinencia

Prior por metadatos del catálogo: ALTA en las 5 (ver `manifest.json`).
Clasificación por títulos (accionable/editorial/ambigua/empleo-otro) y
precisión aparente: PENDIENTES del piloto L3 — `needs_human_review=true`
en las 5. Metodología: `pertinencia.md`. UNKNOWN antes que certificar.

## Comando exacto del piloto (L3 — NO ejecutar sin autorización expresa)

Secuencial, 5 GET máximo, una invocación por fuente (cada una hace red real
vía transporte instrumentado, `max_requests=1`):

```bash
cd apps/api
for s in novo-nordisk-grants grants-gov-forecast minciencias ukri-opportunities innpulsa; do
  python3 -m app.audit.cli --mode live-probe --allow-network --source-key "$s" --output "../../reports/lote-1-preflight/piloto-$s"
done
```

Ver `run_pilot.sh` (documenta el comando; no ejecutado en este encargo).

## Dry-runs verificados (0 red)

`dry-runs/*.plan.json` — generados con
`--mode live-probe --source-key <k> --dry-run` (ruta que por construcción
nunca crea el cliente HTTP; cubierto por test).
