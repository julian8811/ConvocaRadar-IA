# Piloto 041 — evidencias trazables (X4, issue #62)

Origen: trabajo 100% offline con artefactos ya existentes. CERO red en X4.
Fuentes primarias reales del piloto X3 (verificadas el 2026-10-13 con 5 GET de
cortesía, según `test_041_batch_seeds.py` / `test_041_batch_pilot.py`):

- `apps/api/tests/test_041_batch_pilot.py` — fixtures (título, URL, deadline/status) por fuente.
- `apps/api/tests/test_041_batch_parse.py` — HTML mínimo por fuente usado con fetch mockeado.
- `apps/api/app/db/seed.py` — 5 seeds 041 (`enabled=False`, `tier experimental`).
- `docs/expansion-catalogo-041/matriz-041-candidatos.{csv,json,xlsx}` — decisiones X1/X2.

## Hallazgo de trazabilidad (honesto)

**Ningún HTML real del piloto quedó guardado.** Los tests X2/X3 usan HTML mínimo
sintético inline + fixtures (título/URL/fecha) en memoria. Por eso X4 reconstruye
fixtures *representativos* (mismo títulos/URLs/patrones documentados, estructura
`main > article > h2 > a` + línea de fecha/estado) SIN fetchear, y declara cada
desviación respecto a lo documentado.

## Fuente de cada fixture

### `fixture-eu-life-calls-cinea.html` (reconstruido, NO fetch real)

Etapa 0 (gate): cero fechas inventadas. Solo la card 1 trae fecha (real
documentada); el resto declara cierre `unknown` (cards sin linea de fecha;
el parse emite `close_date None` + marca unknown, nunca `open`).

| # | Título en fixture | Fuente documentada | Fecha en fixture | Declaración |
|---|---|---|---|---|
| 1 | LIFE 2026 Standard Action Projects - Circular Economy and Zero Pollution | matriz `ejemplo_titulo` + pilot fixture `sap-circular-economy` | Deadline 22 September 2026 | Fecha real documentada (matriz `ejemplo_cierre` 2026-09-22). Al 2026-10-13 está **vencida**: sirve de pin de filtro de vencidas. |
| 2 | LIFE 2026 Nature and Biodiversity Standard Action Projects call for proposals | pilot fixture `sap-nature-biodiversity` (deadline unknown) | `unknown` (sin fecha) | Título/URL documentados; el piloto la marcó `unknown` y la etapa 0 eliminó la fecha sintética futura que traía el fixture X4. Revalidar contra el portal en el gate de activación. |
| 3 | CINEA is hiring: Project Officer (job vacancy) | patrón anti-ruido X3 (`NOISE_KEYWORDS`: empleo/jobs) | sin fecha | **Card sintética** que instancia el ruido documentado (la fuente real mezcla vacantes). Pin de pertinencia. |
| 4 | News: LIFE Awards 2026 winners announced | patrón anti-ruido X3 (noticias/press) | sin fecha | **Card sintética** de ruido editorial. Pin de pertinencia. |

### `fixture-fundacion-biodiversidad.html` (reconstruido, NO fetch real)

Etapa 0 (gate): cero fechas inventadas. Las cards relevantes declaran
cierre `unknown` (sin linea de fecha; el parse emite `close_date None` +
marca unknown, nunca `open`).

| # | Título en fixture | Fuente documentada | Fecha en fixture | Declaración |
|---|---|---|---|---|
| 1 | Convocatoria para proyectos de Educacion Ambiental ... desinformacion climatica | matriz `ejemplo_titulo` + pilot fixture | `unknown` (sin fecha) | Título/URL documentados (matriz `ejemplo_url`, importe 7M EUR). La matriz dice `ejemplo_cierre: 2026 (ver BOE/bases)`; la etapa 0 eliminó la fecha sintética futura del fixture X4. Revalidar fecha real en el gate. |
| 2 | Convocatoria renaturalizacion y resiliencia de ciudades 2026 | pilot fixture `convocatoria-infraestructura-verde-ciudades-2026` (unknown) | `unknown` (sin fecha) | Título/URL documentados (importe 9M EUR FEDER). La etapa 0 eliminó la fecha sintética pasada del fixture X4 (el filtro de vencidas queda pineado por la card LIFE 2026-09-22 + test inline). |
| 3 | Oferta de empleo: tecnico de proyectos | patrón anti-ruido (oferta laboral) | sin fecha | **Card sintética** de ruido. Pin de pertinencia. |
| 4 | Noticia: memoria anual 2025 | patrón anti-ruido (noticias/prensa) | sin fecha | **Card sintética** de ruido. Pin de pertinencia. |

## Evidencia consolidada del piloto (`evidencia-piloto-041.json`)

Títulos, enlaces, fechas, clasificaciones y duplicados ENTRE las cinco y contra
el catálogo 203, tal como los dejó X3. Ver archivo JSON + resumen abajo.

## Clasificaciones X3 (veredicto piloto, heredado sin cambios)

- `eu-life-calls-cinea`: GO (fuente oficial CINEA, distinta del agregador).
- `fundacion-biodiversidad-convocatorias`: GO parcial (elegibilidad ES/UE restringida).
- `fondo-accion-convocatorias`: GO con nota → revisión humana en X4 (sin conector).
- `fontagro-convocatorias`: HOLD (ciclo anual, verificar ventana antes de activar).
- `biodiversa-calls`: HOLD (revalidar elegibilidad por agencia nacional).

## Duplicados

- ENTRE las cinco: 0 (dominios/URLs/títulos disjuntos, pin en `test_041_batch_pilot.py`).
- Contra catálogo 203: 0 keys nuevas duplicadas; casos documentados:
  - LIFE vs `eu-funding-portal-international`: dominios disjuntos
    (`cinea.ec.europa.eu` vs agregador `eufundingportal.eu`) → pin semántico en X4.
  - NIH → filtro sobre grants-gov (sin key); Innovate UK → solapa `ukri-opportunities`;
    SENNOVA → parcial `sena-convocatorias`. Sin keys nuevas en los tres casos.
