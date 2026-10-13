# Re-probe redirects tras fix R-A — 2026-10-12

Re-probe de las 15 fuentes que en la ronda previa dieron `blocked_by_policy`
(evidencia base: `live-probe-<fuente>-20261012/live-probe-real.json` con
`reason: redirect a host no autorizado/privado`), tras el fix R-A
(redirects mismo-dueño: mismo host/subdominio, mismo registrable, mapeo
explícito; veto multi-tenant). Commit fix: `51ae5c7`.

## Método (idéntico para las 15, secuencial)

- Runner: `app/audit/live_probe.py` del worktree (`run_live_probe` +
  `build_httpx_transport`), sin modificar código.
- 1 corrida por fuente, secuencial, pausa 2 s entre fuentes, UA
  `ConvocaRadar-preflight/1.0`, `follow_redirects=False` (cada salto lo
  decide el probe).
- Budgets del probe: `timeout_s=15`, `total_budget_s=60`,
  `max_bytes_per_page=2000000`, `max_redirects=3`, `retry_max=2`,
  `max_requests_per_source=2` (**hard cap: nunca >2 requests/fuente**).
- `authorized_hosts` = `allowed_domains` del seed + host del `base_url`.
- STOP ante WAF/403/429 (`live_blocked`/`live_transient`, revisión humana),
  sin reintentos (el probe no reintenta: 0 retries en las 15).
- Sanitización: URLs sin query/fragment; solo muestra de títulos (≤10).

## Tabla predicho-vs-real

| Fuente | Redirect chain observada | Veredicto | Predicción R-A | Acierto |
|---|---|---|---|---|
| iie-programs | `www.iie.org/programs/` → `/scholarships-programs/` (host autorizado) | `live_ok` 200, 371 KB, 12 títulos | pasa | **sí** |
| acumen-fellowship | `acumen.org/fellowship/` → `/acumen-academy/` (host autorizado) | `live_ok` 200, 461 KB, 7 títulos | pasa | **sí** |
| rhodes-scholarship | `…/apply/` → `…/scholarships/applications/` (host autorizado) | `live_ok` 200, 44 KB, 3 títulos | pasa | **sí** |
| eu-culture-moves-europe | `…/culture-moves-europe` → `…/culture-moves-europe/home` (host autorizado) | `live_ok` 200, 109 KB, 13 títulos | pasa | **sí** |
| mintic-convocatorias | `…/Convocatorias/` → `…/portal/715/w3-propertyvalue-111099.html` → +1 salto (mismo host; cadena > cap) | `over_budget` req=2, revisión | pasa | **parcial** (salto 1 mismo-host OK, cadena excede cap 2) |
| camara-comercio-bquilla | `…/convocatorias/` → `…/convocatorias-ccb/` → +1 salto (mismo host; cadena > cap) | `over_budget` req=2, revisión | pasa | **parcial** (ídem) |
| colombia-productiva | `www.colombiaproductiva.com` → `www.innpulsacolombia.com/…` (**mapeo explícito documentado**) | `live_ok` 200, 150 KB, título "Colombia Productiva ahora es iNNpulsa Colombia" | pasa | **sí** |
| conacyt-mexico | `conahcyt.mx` → `secihti.mx/convocatorias/` (**mapeo explícito documentado**) | `live_ok` 200, 180 KB | pasa | **sí** |
| uniandes-oportunidades-investigacion | `investigacioncreacion.uniandes.edu.co` → `uniandes.edu.co/…` (host autorizado, seed) → **TLS falla** en destino | `live_blocked` req=2, revisión (`CERTIFICATE_VERIFY_FAILED` + marcador WAF en cuerpo del 301) | pasa | **parcial** (el redirect SÍ pasó la política; el bloqueo es red/TLS, no política) |
| proinnovate-calendario | `calendario.proinnovate.gob.pe` → `cdn.www.gob.pe` | `blocked_by_policy` req=1, revisión | pasa | **no** (el mapa R-A cubre `cdn.gob.pe` pero el target real es `cdn.www.gob.pe`, registrable `www.gob.pe` ≠ par) |
| nz-manaaki-scholarships | `www.mfat.govt.nz` → `www.nzscholarships.govt.nz` | `blocked_by_policy` req=1, revisión | pasa | **no** (`nzscholarships.govt.nz` no tiene mapeo explícito; `govt.nz` no hereda por sufijo) |
| mozilla-foundation | `foundation.mozilla.org` → `www.mozillafoundation.org/…` (mapeo explícito OK) → +1 salto (cadena > cap) | `over_budget` req=2, revisión | pasa | **parcial** (salto 1 por mapeo explícito OK, cadena excede cap 2) |
| procolombia-convocatorias | `www.procolombia.co` → `drive.google.com/drive/folders/…` (**host autorizado**: `drive.google.com` está en `allowed_domains` del seed) | `live_ok` 200, 403 KB, **0 títulos** (página Drive JS, muestra nula) | sigue bloqueado | **no** (la allowlist explícita del seed otorga "host autorizado" y el veto multi-tenant NO aplica a hosts explícitos — solo a inferencia mismo-dueño) |
| sena-convocatorias | `oferta.senasofiaplus.edu.co` → `betowa.sena.edu.co/oferta` (**mapeo explícito documentado**) | `live_ok` 200, 377 KB, 24 títulos (ofertas reales) | pasa | **sí** |
| erasmus-plus-opportunities | `…/opportunities-for-organisations` → `…/opportunities/organisations` (host autorizado) | `live_ok` 200, 191 KB, 14 títulos | pasa | **sí** |

**Aciertos: 8 plenos + 4 parciales + 3 fallos de 15.**
Parcial = la regla R-A funcionó en el salto observado pero el veredicto
final quedó pendiente por cap/TLS. Fallo = predicción incorrecta (ver
hallazgos).

## Totales

- Requests totales: **28** (15 fuentes; 13×2 + 2×1; cap ≤2 respetado en todas).
- Veredictos: 9 `live_ok` · 1 `live_blocked` (uniandes, TLS) ·
  2 `blocked_by_policy` (proinnovate, nz) · 3 `over_budget` (mintic, camara, mozilla).
- Retries: 0. WAF/403/429: ningún 403/429 directo; 1 marcador WAF en cuerpo
  301 (uniandes) → STOP con revisión.

## Hallazgos (para el hilo principal, sin cambios de código aquí)

1. **Allowlist explícita > veto multi-tenant (procolombia).** El veto R-A solo
   bloquea *inferencia* mismo-dueño; un host en `allowed_domains` otorga
   "host autorizado" aunque sea multi-tenant. `drive.google.com` está en el
   seed de procolombia → `live_ok` 200 pero muestra nula (0 títulos, página
   JS). Decisión pendiente: mantener `live_ok` con revisión, o sacar Drive
   de la allowlist / tratar Drive como `live_blocked`.
2. **Mapa R-A incompleto (proinnovate).** Target real `cdn.www.gob.pe`
   (registrable `www.gob.pe`) ≠ par mapeado `{proinnovate.gob.pe,
   cdn.gob.pe}`. Decisión pendiente: agregar `www.gob.pe` al par o aceptar
   el bloqueo.
3. **Sin mapeo NZ.** `www.nzscholarships.govt.nz` no tiene par explícito y
   `govt.nz` no hereda por sufijo (correcto por diseño). Decisión pendiente:
   agregar par `{mfat.govt.nz, nzscholarships.govt.nz}` o aceptar el bloqueo.
4. **Cadenas > cap 2 (mintic, camara, mozilla).** Los saltos observados son
   mismo-host/explícitos (la regla R-A funciona), pero la cadena real tiene
   ≥2 saltos. Con `max_requests=2` quedan en `over_budget` sin cadena en la
   evidencia (esa rama no emite `redirect_chain`; las URLs vistas sí quedan
   en `evidence.urls`). Decisión pendiente: re-probe puntual con cap mayor o
   revisión manual.
5. **Uniandes: el redirect pasó la política; falló la red.** Destino
   `uniandes.edu.co` autorizado, pero TLS `CERTIFICATE_VERIFY_FAILED` y el
   cuerpo del 301 (167 B, no persistido — el probe no guarda cuerpos)
   contiene un marcador WAF → `live_blocked`. Revisión manual pendiente.

## Archivos

- `<fuente>.re-probe.json` (15): outcome completo por fuente
  (`status`, `http_status`, `requests_made`, `evidence` con `urls`,
  `redirect_chain`, `reason`, muestra de títulos) + campo `predicted`.
- `RESUMEN.md` (este archivo).

## Pendientes

- Decisión hilo principal sobre hallazgos 1–4 (allowlist Drive, pares
  `www.gob.pe` / `nzscholarships.govt.nz`, cap para cadenas largas).
- Revisión manual: uniandes (TLS+WAF), mintic/camara/mozilla
  (`over_budget`), procolombia (`live_ok` con muestra nula).
- Ningún reintento cursado; todo re-probe futuro respeta cap ≤2/fuente salvo
  autorización expresa.
