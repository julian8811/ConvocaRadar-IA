# Informe de Salud de Fuentes — Docker Local (PostgreSQL) 21/07/2026

## Resumen Ejecutivo

| Indicador | Valor |
|---|---|
| **Total fuentes** | 127 |
| **Habilitadas** | 112 |
| **Deshabilitadas** | 15 |
| **Auto-pausadas** | 15 (11 por 0 ítems consecutivos + 4 por fallos) |
| **Sanas** | 94 (según dashboard) |
| **Degradadas** | 13 (según dashboard — 11 auto-paused + 2 degraded runs) |
| **Fallando** | 5 |

---

## 1. FUENTES FALLANDO (5)

| # | Key | Nombre | Error | Causa Raíz |
|---|---|---|---|---|
| 1 | `fondecyt-chile` | FONDECYT Chile | **HTTP 403** anid.cl | WAF/Cloudflare bloquea el User-Agent del bot |
| 2 | `interamerican-foundation` | IAF Grants | **HTTP 403** iaf.gov | WAF Apache — devuelve HTML "403 Forbidden" |
| 3 | `sena-convocatorias` | SENA Oferta Educativa | **Dominio fuera de allowed_domains** | URL redirige a dominio no whitelisteado |
| 4 | `innovamos-fid` | Innovamos — FID | **Innovamos page unavailable** | Sitio caído o cambió de URL |
| 5 | `innovamos-global-innovation-fund` | Innovamos — Global | **Innovamos page unavailable** | Mismo problema — plataforma Innovamos |

---

## 2. FUENTES AUTO-PAUSADAS (11) — Degradadas

Estas fuentes están habilitadas pero el sistema las pausó automáticamente tras múltiples corridas con 0 ítems. Agrupadas por causa:

### 2.1 Selector genérico no calibrado (8)

| Key | Nombre | Último error |
|---|---|---|
| `acac-colombia` | ACAC Convocatorias Científicas | — |
| `agrosavia-convocatorias` | AGROSAVIA | — |
| `argentina-investigacion` | Argentina.gob.ar Ciencia | — |
| `cfe-uruguay` | CFE Uruguay Investigación | — |
| `findeter-convocatorias` | Findeter | — |
| `finep-brasil` | FINEP Brasil | — |
| `uniandes-investigacion` | Uniandes Investigación | — |
| `world-bank-procurement` | World Bank Procurement | — |

**Causa**: `GenericHtmlConnector` no encuentra ítems porque los selectores heurísticos no coinciden con la estructura de estos portales.

### 2.2 Playwright budget agotado (2)

| Key | Nombre | Error |
|---|---|---|
| `fapemig-brasil` | FAPEMIG Minas Gerais | `Playwright budget exhausted — max 5 concurrent` |
| `sida-sweden` | SIDA Suecia | `Playwright budget exhausted — max 5 concurrent` |

**Causa**: Estas fuentes requieren JS rendering pero el límite de 5 sesiones Playwright concurrentes se agota durante el sweep.

### 2.3 API legacy (1)

| Key | Nombre | Error |
|---|---|---|
| `cordis-h2020` | CORDIS Horizon 2020 | — |

**Causa**: API de CORDIS cambió de endpoint o ahora requiere autenticación.

---

## 3. FUENTES DESHABILITADAS (15)

Desactivación manual o por política. Sin ejecuciones recientes:

| Categoría | Fuentes | Cantidad |
|---|---|---|
| **URL legacy / endpoint caído** | bndes-brasil, caf-convocatorias, colombia-cientifica, eu-funding-tenders, fonacyt-bolivia, koica-korea, minsalud-convocatorias, senescyt-ecuador | 8 |
| **Institución sin conector** | embrapii-brasil, icfes-convocatorias, ideam-convocatorias, sebrae-brasil, uis-investigacion, uptc-investigacion | 6 |
| **Duplicada** | fondo-nacional-garantias | 1 |

---

## 4. CAUSAS RAÍZ IDENTIFICADAS

| Causa | Fuentes afectadas | Gravedad |
|---|---|---|
| **Selector genérico insuficiente** | 8 auto-paused + ~2 degraded | Alta — 10 fuentes produciendo 0 ítems |
| **WAF/Cloudflare (HTTP 403)** | 2 fallando | Media — requiere Playwright fallback o User-Agent |
| **Innovamos caído** | 2 fallando | Baja — depende de tercero, fuera de nuestro control |
| **Playwright budget** | 2 auto-paused | Media — escalar límite o migrar a HTTP puro |
| **Dominio no whitelisteado** | 1 fallando | Trivial — fix de 1 línea |
| **Disabled sin plan** | 15 inactivas | Baja — son intencionalmente desactivadas |

---

## 5. RECOMENDACIONES POR PRIORIDAD

### Inmediatas (triviales)

| # | Acción | Fuentes | Esfuerzo |
|---|---|---|---|
| 1 | Agregar dominio a `allowed_domains` | sena-convocatorias | 1 línea |
| 2 | Activar `playwright_fallback=True` | fondecyt-chile, interamerican-foundation | `connector_config` por fuente |
| 3 | `release_recoverable_sources.py` | acac-colombia, agrosavia, argentina-investigacion, cfe-uruguay, findeter, finep, uniandes, world-bank | Script ya existe |

### Corto plazo (selectores)

| # | Acción | Fuentes |
|---|---|---|
| 4 | Crear `ConfigurableHtmlConnector` con selectores específicos | Las 8 auto-paused por selector + dane, sgc |
| 5 | Aumentar `PLAYWRIGHT_MAX_CONCURRENT` a 10 | fapemig-brasil, sida-sweden |

### Estratégico

| # | Acción |
|---|---|
| 6 | Activar `developmentaid-tenders` (ya implementado) — compensa ~20 fuentes individuales |
| 7 | Auditoría de las 15 disabled: ¿eliminar definitivamente o plan de recuperación? |
