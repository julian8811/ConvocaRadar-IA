# Etapa 1 — dry-run contra HTML vivo (gate 041/042, issue #62)

Presupuesto de red: **2 GETs totales** (1 CINEA + 1 FB), secuenciales,
timeout 15s, UA repo `ConvocaRadarBot/1.0`, 1 solo intento cada uno
(sin reintentos), sin seguir links, sin playwright, **cero escrituras DB**.
Ver `fetch-log.json` (status, bytes, tiempos, redirect chain).
Presupuesto agotado: todo el analisis posterior es offline sobre ese HTML.

## CINEA (`eu-life-calls-cinea`) — veredicto: HOLD (0 abiertas hoy)

Fetch: 200, 107.558 bytes, 0,95s, sin redirects.

| Título real extraído | URL | Cierre real | Pertinencia | Elegibilidad | Duplicados |
|---|---|---|---|---|---|
| SAPs Circular Economy and Zero Pollution – Environment | `cinea.ec.europa.eu/funding-opportunities/.../standard-action-projects-saps-circular-economy...` | **2026-09-22 (vencida)** → filtrada por conector | grant real | UE/asociados LIFE | dominio disjunto vs agregador `eufundingportal.eu` |
| SAPs Climate Governance and Information | `.../climate-governance-and-in...` | **2026-09-22 (vencida)** → filtrada | grant real | idem | idem |
| Framework Partnership Agreements (FPA OG) | `.../framework-partnership-agr...` | **2026-09-08 (vencida)** → filtrada | grant real | idem | idem |
| SGA OG to NGOs | `.../specific-operating-grant-...` | **2026-09-22 (vencida)** → filtrada | grant real | ONGs UE | idem |
| LIFE Calls 2025…2019 (7 links archivo) + CINEA Website | varias `cinea.ec.europa.eu/...` | sin fecha → `unknown`, `validate` rechaza | índice/archivo, no calls | n/a | n/a |

- Ruido empleo/noticias en la muestra relevante: **0**.
- `parse-cinea.json`: 9 candidatos del conector, los 9 con `validate_ok=false`
  (4 vencidas filtradas antes; 5+ archivo como unknown). Cero publicables: correcto.
- La pagina declara que las calls viven en el Funding & Tenders Portal
  (el agregador 203 ya las cubre por otro dominio).
- HOLD: reactivar cuando publiquen calls 2027 con deadlines futuros. El filtro
  de vencidas y la marca unknown quedaron validados contra HTML real.

## Fundación Biodiversidad (`fundacion-biodiversidad-convocatorias`) — veredicto: HOLD (markup + sin fechas en listado)

Fetch: 200, 176.282 bytes, 2,4s, sin redirects.

| Título real en página | URL | Cierre real | Pertinencia | Elegibilidad | Duplicados |
|---|---|---|---|---|---|
| Convocatoria Educación Ambiental y desinformación climática | `.../otras_convocatorias/convocatoria-para-proyectos-de-educacion-ambiental...` | **no figura en el listado** | grant real (coincide matriz X1, 7M EUR) | ES/UE s/bases | — |
| Convocatoria BiodivFuture (Biodiversa+) | `.../convocatorias_biodiv/convocatoria-biodivfuture...` | **no figura en el listado** | grant real | consorcios 3+ países | **solape con `biodiversa-calls` (HOLD): misma joint call espejada; resolver antes de activar cualquiera** |
| Convocatoria apoyo políticas públicas competencia estatal | `.../otras_convocatorias/convocatoria-para-el-apoyo-y-la-participacion...` | **no figura en el listado** | grant real | estatal ES | — |
| Convocatoria ayudas FEDER renaturalización ciudades 2026 | `.../convocatorias_feder/convocatoria-de-ayudas-feder-para-el-impulso...` | **no figura en el listado** | grant real (coincide matriz X1, 9M FEDER) | ES s/bases | — |
| Becas de formación / Becas Generación Clima | `.../convocatoria-de-becas-de-formacion...` | **no figura en el listado** | borderline (becas formación, no I+D) | personas físicas | — |
| Ofertas de empleo (2 links) | `.../ofertas-de-empleo/` | n/a | **ruido** (filtro `is_noise` lo descarta) | n/a | n/a |

- `parse-fundacion-biodiversidad.json`: **0 candidatos** — la página real no usa
  `<main>` ni `<article>` (142 anchors fuera del selector del conector).
  Es el NO-GO típico del plan (cambio de markup → selectores + fixtures + tests).
- Aun con selectores corregidos: el listado no trae fechas (irían en fichas
  detalle = más GETs, fuera del presupuesto del gate) → todo saldría `unknown`
  y `validate` lo rechazaría. HOLD hasta definir estrategia de fechas.
- NO se modifica código en esta etapa (el gate ordena detenerse tras la evidencia).

## Criterio GO etapa 1 (plan): NO alcanzado en ninguna fuente

≥1 candidato abierto real con `close_date` parseada: CINEA 0 (todo vencido),
FB 0 (markup + sin fechas). **Etapa 2 NO autorizada por esta evidencia.**
