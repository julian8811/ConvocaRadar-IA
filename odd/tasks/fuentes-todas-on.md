# Todas las fuentes ON — feature ODD

## Objective
Llevar las 201 fuentes del catálogo a verde con extracción real: cada fuente en `success` con ítems, o cuarentenada con motivo verificable + decisión del usuario si el sitio está muerto del otro lado.

## Problem
Foto real del sweep force (ventana 3h, 201 keys agrupadas por firma):
- 172 trabajando por diseño: 81 `success+duplicado`, 61 `success+duplicado|ruido`, 15+14 `success` con `url_muerta` parcial, 1 limpio. Filtros (dedupe/ruido) haciendo su trabajo: NO tocar.
- 19 `degraded silent-zero`: 0 ítems, sin error, sin cuarentena (camara-comercio-bogota, conacyt-mexico, dane-convocatorias, developmentaid-tenders, ...). Falla silenciosa de extracción: selector gastado, sitio cambiado o página vacía.
- 6 `degraded quar:ruido`: todo lo extraído clasificado ruido (aladi, camara-comercio-cali, danida, fapemig, procolombia-inversion, rockefeller...). Umbral agresivo o páginas cambiadas.
- 4 `failed timeout`: apc-colombia, ascun-convocatorias, novo-nordisk-grants, world-bank-procurement (sitios lentos >180s).

## Why
Pedido explícito: todas las fuentes funcionando, con ODD e iteración en servidor.

## Scope
- IN: diagnóstico por clase de raíz (nunca una por una), fixes de conectores/umbrales/timeouts en `main` local con tests, PR + port a rama server + verificación por fuente (`POST /sources/{id}/run`) y sweep force final de cierre.
- OUT: reescribir extractores sanos; fixes infinitos en sitios muertos del otro lado (van a cuarentena con motivo + decisión del usuario); Render/Vercel.
- Definición cumplida: 201 en `success` con ítems, salvo sitios muertos verificados (cuarentena + motivo + sign-off).

## Constraints
- Server: solo agregados y single-source runs para iterar rápido (nada de forces completos por prueba); credenciales nunca en repo/memoria; valores solo server-side.
- TDD strict en fixes de código (RED con probe/run por fuente antes del fix, GREEN después, triangulación con suite conectora). Excepción documentada para umbrales/timeouts si no hay RED ejecutable.
- Commits work-unit Conventional en feature branch local; PR; port a server; push/merge los decide el usuario (delegado "todo" en este flujo, como T1–T7).
- Credenciales/secretos: jamás en repo, memoria ni chat más allá de lo expuesto (rotación al cierre).

## Tasks
- [x] **T1 (P0)** ✅ Triage 5 peores con runs individuales + runs-list final (un POST repetido mostró snapshots progresivos confusos; se re-verificó con estado final). Dictamen: (A) camara-bogota/dane = 0 ítems + warn `DOM hash changed` → selectores gastados tras rediseño; (B) aladi/camara-cali/danida = todo a cuarentena `ruido` → extractor OK, clasificador rechaza todo.
- [x] **T2 (P0)** ✅ Parcial verificado en servidor: cherry-pick `731ceea` limpio + rebuild api/worker + reseed-force (201 updated, faperj con 11 selectores) → **faperj-brasil: success 50 ítems** (estaba en 0). findeter sigue en 0: el fix challenge era necesario pero insuficiente (DOM cambiado, parse vacío) → pasa a lista dura de T3. Infra aprendida: imágenes sin mounts (rebuild obligatorio), metadata solo vía reseed-force, auto-pause con cooldown 24h.
- [ ] **T3 (P0)** Fixes clase A parte 2 (resto): mismo ciclo. Ruta: delegada.
- [ ] **T4 (P1)** Clase B (6 ruido-only): revisar clasificador/umbral vs contenido real; fix o dictamen "sitio cambiado" con evidencia. Mismo ciclo PR+port+verify. Ruta: delegada.
- [ ] **T5 (P1)** Clase C (4 timeouts): estrategia por fuente (timeout específico, reintentos, simplificar fetch); verify. Si el sitio no responde ni con eso, cuarentena con motivo. Ruta: delegada o padre según tamaño.
- [ ] **T6 (P1)** Cierre: force sweep final + foto por firma; 201 en success-con-ítems o lista de muertos con motivo para sign-off del usuario. Ruta: padre inline.

## Acceptance
- 201/201 `success` con ítems>0 en ventana del sweep de cierre, o muertos verificados con motivo + sign-off.
- Cero `silent-zero` sin dictamen; cero timeouts sin estrategia.
- Tests nuevos en verde; ramas/PRs documentados aquí.

## Progress
- 2026-10-10: doc creado (6 tareas). Foto por firma verificada server-side (201 keys, 3h). Mirror Engram pendiente (sesiones múltiples).
- 2026-10-10: T1 triage completo (padre inline, single-source runs + runs-list). 5/5 en `degraded` 0 ítems: 3 por cuarentena `ruido`, 2 con warn DOM-cambiado sin cuarentena.
- 2026-10-10: T2 verificado live. Mecánica del sistema mapeada: runtime lee `connector_config` de DB (no seed), reseed-force es el camino sancionado, cooldown auto-pause 24h con reactivación automática.
- 2026-10-10: T2 lote1 parcial (writer, rama `feature/fuentes-t2-lote1`, commit `7c8786f`). 12 keys del lote: 2 fixes con tests, 3 dictámenes de sitio-sin-contenido (evidencia abajo, padre decide cuarentena), 7 pendientes (exceden fix mínimo, no tocadas). Diagnóstico con 1 GET respetuoso por página (User-Agent del repo, secuencial). Sin push.
  | key | causa verificada | fix / estado |
  |---|---|---|
  | faperj-brasil | `list_selectors` solo `article`/`main`; la página no tiene ni `<main>` ni `<article>` (editais en `section.corpo-interna > div.tamanho-fonte > p > strong > a[href*='Edital']`, 134 links) | FIX seed (selectores aditivos) + tests. Probe local HTML real: 0 → 50 candidatos, 50/50 pasan pipeline |
  | findeter-convocatorias | falso positivo: snippet analytics PerfDrive (`ssConf validate.perfdrive.com`) disparaba la rama challenge en páginas sanas; página real trae 25 links 2026 y el parse local da 10/10 válidos → el 0 en servidor apunta a challenge WAF real contra IP servidor | FIX `_is_challenge_page` (marcas precisas) + tests; pendiente run single-source del padre para confirmar challenge vs éxito |
  | aladi-convocatorias | `/sitioaladi/convocatorias/` redirige a la home; la home (251 links) no tiene sección convocatorias | DICTAMEN: sección eliminada del otro lado (HTTP 200 final `https://www.aladi.org/`, título `Home - ALADI`, 0 candidatos convocatoria) |
  | camara-comercio-cali | `/convocatorias/` → 404; la home no tiene reemplazo (0 candidatos convocatoria) | DICTAMEN: sección eliminada del otro lado |
  | dane-convocatorias | la categoría solo lista archival 2015/2016 + requisitos; el conector filtra años ≤2022 → 0 correcto | DICTAMEN: sin contenido vigente en la URL (padre: buscar nueva ruta/SECOP o cuarentena) |
  | camara-comercio-bogota | 403 ×2 (urllib + UA browser) | PENDIENTE: sin DOM visible no hay fix de selectores; next = snapshot DOM server-side (padre, probe con playwright) |
  | danida-denmark | la lista vive en tabs JS `Active/Expired Calls` (`/en/danida/calls-for-proposals/` carga, pero el SSR no trae ningún call) | PENDIENTE: requiere render o descubrir endpoint; excede fix mínimo |
  | developmentaid-tenders | conector OK local (40/40 con XML real, `lastmod` fresco 2026-10-09, 253 sub-sitemaps) | PENDIENTE verify-only: server 0 ⇒ fetch bloqueado (Cloudflare) o estado saturado; next = single-source run (padre), sin cambio de código |
  | erc-calls | API v1 muerta: POST con `queryString` en body → 400 (`apiKey`+`text` van por query, POST body vacío = 200); shape v2 distinto (`summary`/`url`/`metadata`, sin `title`/`identifier`) y `text=ERC` devuelve 350k full-text (proyectos `Ended`, no calls abiertas) | PENDIENTE: requiere DSL v2 (filtro calls abiertas) + rewrite de parse; excede fix mínimo |
  | eu-creative-europe-calls | shell JS sin SSR (0 `ecl-card`, 0 refs a funding-tenders, sin calls en h2/h3); las calls reales viven en el portal F&T | PENDIENTE: mismo rediseño que erc-calls |
  | fapemig-brasil | `/pt/menu/editais/` redirige a la home (base desactualizada); el listado canónico `/oportunidades/chamadas-e-editais` es Nuxt CSR (datos en `__NUXT__` JSON posicional; el SSR solo deja basura numérica que cae a `ruido`) | PENDIENTE: requiere conector Nuxt dedicado; excede fix mínimo |
  | finep-brasil | `/oportunidades` y `/chamadas-publicas` (redirige al anterior) SSR sin llamadas (solo link legacy EFPC) | PENDIENTE: requiere descubrir endpoint JS o URL legacy; excede fix mínimo |
 - Tests: `apps/api/tests/test_fuentes_t2_lote1.py` (6 tests, TDD RED→GREEN: parse FAPERJ 0 con config vieja, `ImportError` del helper, guards findeter). Suite conectora relacionada: 110 passed.
 - Hechas: faperj-brasil, findeter-convocatorias (fix) + aladi, cali, dane (dictamen). Pendientes exactas: ccb-bogota, danida, devaid, erc, creative-europe, fapemig, finep (7/12).
- 2026-10-10: T3 lote2 completo local (writer, rama `feature/fuentes-t3-lote2`, sin push; pendiente reseed + runs single-source del padre). 12/12 keys con fix o dictamen. Diagnóstico con GETs secuenciales respetuosos (User-Agent del repo) + parse real con config de seed en memoria.
  | key | causa verificada | fix / estado |
  |---|---|---|
  | jsps-fellowships | sin `<article>`/`<main>`; programas en content units `div.ww-text` (Standard, Short-term PE/PA, Summer) | FIX seed (1 selector aditivo `div.ww-text a[href*='/e-fellow/e-']`) + tests. Live: 0 → 4 candidatos |
  | jsps-kakenhi-grants | sin `<article>`/`<main>`; secciones en `div.ww-text` mezcladas con utilitarias (How to apply, Inquiries) | FIX seed (1 selector aditivo comma-OR preciso `grants01/lsrp/multi-year_fund`, excluye utilitarias) + tests. Live: 0 → 3 candidatos |
  | rockefeller-foundation | `/grants/` → 301 `/our-grants/`; sin `connector_config` (GenericHtml extraía junk "Our Grants \| RF" → cuarentena `ruido`) | FIX seed (`connector_config` nuevo, per-source: `residency-program/big-bets-fellowships//convenings/`; regla global `eventos` intacta) + tests. Live: 2 junk → 4 programas + 2 self-refs JSON-LD preexistentes |
  | proinnovate-calendario | base → 302 a `calendario-de-concursos-2026.pdf` (1.5MB); `source_type html` parseaba bytes → 0 | FIX seed (`source_type` → `pdf`, se retira `connector_config` HTML muerto) + tests. Live vía PdfConnector: 0 → 9 candidatos |
  | urosario-fondos-concursables | base redirige a landing cuyo `<article>` rinde 0; calls 2026 en subpágina fondos-concursables (tabs `div[id*='tab-convocatoria']`, 5 bloques) | FIX seed (base → subpágina + selector tab ANTEPUESTO — excepción documentada: `article` calza pero rinde 0, lo aditivo al final no surte efecto) + tests. Live: 0 → 5 candidatos |
  | idb-calls-proposals | página viva (200, 178KB) pero texto literal ×2: "There are no open calls for proposals at this time." | DICTAMEN: sin contenido vigente (clase T2 dane). Sin cambio de código |
  | sicon-bogota-estimulos | aviso oficial (2KB): SICON Drupal retirado, canal oficial ahora `https://cultured.gov.co/` | DICTAMEN: migrado del otro lado; nueva base propuesta para decisión del padre. Sin cambio de código |
  | procolombia-inversion | `/es/convocatorias` → 404; reemplazo `buscador-oportunidades-inversion` SSR sin proyectos (Views AJAX, 57 scripts) | DICTAMEN: sección eliminada + reemplazo JS (excede mínimo). Sin cambio de código |
  | horizon-europe-sedia | API search v1 muerta: POST con `apiKey`+`queryString` en body → 400 `Required request parameter 'apiKey'...` (apiKey ahora por query, shape v2 sin `title`/`identifier`) | PENDIENTE: misma clase que erc-calls T2 (requiere DSL v2 + rewrite). Sin cambio de código |
  | msca-funding | `article` sin links; calls reales en portal F&T (0 refs `funding-tenders`, sin JSON-LD, sin iframe) | PENDIENTE: requiere conector portal F&T (misma clase erc/creative-europe). Sin cambio de código |
  | sloan-grants | 403 Cloudflare "Just a moment..." con UA repo Y browser | PENDIENTE: WAF (clase T2 ccb-bogota); next snapshot DOM server-side/playwright (padre). Sin cambio de código |
  | startup-chile | SSR sin links de oportunidad en contenido (solo brochures PDF; programas solo en nav + secciones Vue sin links) | PENDIENTE: excede mínimo; sugerido split en 3 subfuentes build/growth/ignite (decisión padre). Sin cambio de código |
  - Tests: `apps/api/tests/test_fuentes_t3_lote2.py` (10 tests, TDD RED 0/10 → GREEN 10/10: asserts de seed + parse de fixtures DOM-real; triangulación anti-junk: stories/How-to-apply/Inquiries excluidos). Pinning actualizado: `test_026_batch1_parse` (retira fixture HTML proinnovate migrado a pdf), `test_026_batch1_seeds` (rama pdf sin config), `test_030_batch_seeds` (nueva URL urosario). Suite relacionada: 226 passed.
  - Hechas (fix): jsps-fellowships, jsps-kakenhi-grants, rockefeller-foundation, proinnovate-calendario, urosario-fondos-concursables (5/12). Dictamen cerrado: idb, sicon, procolombia (3/12). Pendientes exactas (exceden fix mínimo): horizon-europe-sedia, msca-funding, sloan-grants, startup-chile (4/12).
  - Notas para el verify del padre: (a) urosario: 2/6 títulos (`ECI 2026`, `ONE LAB UR CONECTA 2026`) pueden caer a cuarentena `ruido` por la regla SECOP de `is_noise_title` (pipeline, NO tocada — ajuste sería T4 clase B); (b) rockefeller: los 2 self-refs JSON-LD preexistentes los maneja cuarentena como antes; (c) proinnovate PDF: sin precedente de pipeline para `source_type pdf` (fate por verificar en server); (d) mecánica igual que T2: reseed-force + rebuild si aplica.

## Verification evidence
- Grupos: 81+61+15+14+1 sanos; 19 silent-zero; 6 ruido-only; 4 timeout. (Claves ejemplo en el handoff de la sesión.)

## Next step
- T2: fixes clase A parte 1 (writer: mapear keys→conectores/seeds, actualizar selectores con tests, PR, port, verify por fuente).
