# Servidor operativo + fuentes ON — feature ODD

## Objective
Dejar el observatorio del servidor (10.3.1.128) con todas las funciones verificadas y las 201 fuentes del catálogo barriendo sin errores sistémicos.

## Problem
1. Login bloqueado: la DB tiene UN solo usuario (`consultor.ceitto@colmayor.edu.co`, admin) y la cuenta probada en el form no coincide → 401 determinístico. Causa candidata: `ADMIN_PW` nunca existió en el `.env` del servidor, así que `_seed_admin_user` hizo skip siempre (`seed.py:24-27`).
2. Al server le falta `cd0ea27` (fix `isAbortError` DOM en web) y conserva `docker-compose.prod.yml` en disco (ya eliminado en `main` por T4).
3. Estado real del stack (verificado 2026-10-10, corrección de un diagnóstico previo truncado): api/worker/web/postgres/minio/backup TODOS Up y healthy; API responde vía proxy `/observatorio/api/v1/...` (422 en body vacío = ruta viva que valida).

## Why
Autorización explícita del usuario: intervenir e iterar hasta funciones OK + fuentes ON, con ODD.

## Scope
- IN: port `cd0ea27` a rama server + rebuild web + verify; `rm` del overlay en disco del servidor; crear o resetear credencial admin funcional; sweep run-all e2e + verificación de funciones y fuentes.
- OUT: código nuevo en `main` local (si hace falta fix, va por PR como siempre); Render/Vercel; rotación de secretos (el usuario la hace al cierre).
- Definición honesta de "fuentes ON": 201/201 `enabled` en catálogo + sweep que completa sin errores sistémicos; sitios individualmente muertos → cuarentena con motivo (no fixes infinitos por sitio).

## Constraints
- Intervención remota autorizada (destino, inspección+operación, SSH ubuntu). Credencial/contraseñas: NUNCA en repo ni memoria; en chat solo lo imprescindible para operar (el usuario rota todo al cierre); valores generados/leídos solo dentro del servidor.
- Commits en servidor: work-units Conventional en su rama server, sin pushes a `origin/main` desde ahí salvo orden expresa.
- TDD strict con excepción documentada para ops (verificación funcional observada en vez de RED).
- Delivery `ask-on-risk`; cada tarea registra evidencia + commit/revisión.

## Tasks
- [x] **T1 (P0 server)** ✅ Rama server `cd5cd5a` (cherry-pick limpio de `cd0ea27`), overlay borrado del disco (`chore(server)`), rebuild web + `up -d` healthy, login page 200. Ruta: padre inline.
- [x] **T2 (P0 server)** ✅ Segundo admin `admin@convocarad.ar` (default del código, `seed.py:24`) creado con password fuerte generado server-side; `POST /observatorio/api/v1/auth/login` → 200 verificado server-side. Opción elegida ante "sigue" sin respuesta: prefill inexistente (claves vacías en `.env`), así que default del código + password entregado una vez en chat.
- [x] **T3 (P0 e2e)** ✅ Task `b1f90bda` `success`: 201/201 processed, failed=0 a nivel task; 201 runs (172 success / 25 degraded / 4 failed por `TimeoutError` individual), `items_found=1906`, `items_created=24`, 29 runs en cero. Diagnóstico previo: `due=0` sin force era cadencia correcta (último barrido hacía <24h), no bug.
- [x] **T4 (P1)** ✅ 14 endpoints GET vía proxy con token, todos 200: `/me`, `/health`, 4× dashboard, `/sources/health`, `/opportunities`, `/reports`, `/alerts/count`, `/tasks`, `/faculties`, `/admin/metrics`, `/organizations/current`. Dashboard real: 15457 oportunidades (1441 abiertas); métricas: 201/201 activas, degraded 28, failing 4, embeddings 100%, pending_alerts 0. Incidente en el camino: rate-limit de login (5/hora) por logins repetidos del propio diagnóstico → resuelto con `restart api` (limiter in-process) + token único reutilizado.

## Acceptance
- Login 200 + cookie; dashboard y funciones T4 en verde.
- Run-all `completed`; 201/201 enabled; solo fallas por-fuente cuarentenadas.
- Server sin overlay en disco; rama server con `cd0ea27`.

## Progress
- 2026-10-10: doc creado. Diagnóstico read-only completo: stack full Up (corrección: un `docker ps` truncado había sugerido solo-web), DB `users=1`/`sources 201/201 enabled`, proxy `/observatorio/api/v1/*` vivo (422 en vacío), `ADMIN_*` ausente en `.env` (causa probable del 401), `POSTGRES_USER=convocaradar` (compose), puerto 8000 directo cerrado por diseño (solo web publicada). Mirror Engram pendiente (sesiones múltiples).
- 2026-10-10: T1+T2 ejecutados por el padre inline (bounded, sin secretos en comandos salvo entrega única en chat). Fetch `origin/main` → `28bbfd1` OK en el servidor; cherry-pick limpio; rebuild web recupera `convocaradar-web-1` healthy en ~20s. Prefill `NEXT_PUBLIC_LOCAL_*` vacío en `.env` (líneas 23-24) + `.env:14` con basura `IA` (rompe `source` con `sh`, no fatal). Segundo admin creado; login 200 server-side. Commits server: `cd5cd5a` + `chore(server)` overlay.
- 2026-10-10: T3 sweep force (`b1f90bda`) completado en ~15 min: 201/201, failed task 0. Top extracción: innpulsa(73), cost-open-calls(61), fondo-emprender(50), fapesp(50). 4 failed = `TimeoutError` individual (apc-colombia, world-bank-procurement, novo-nordisk-grants, ascun-convocatorias); 25 degraded parciales. Sin errores sistémicos: extracción lexbor confirmada en vivo.
- 2026-10-10: T4 funciones verificadas (14/14 en 200). Aprendizajes: reutilizar UN token por sesión de diagnóstico (el rate-limit 5/hora es por email); el limiter es in-process así que `restart api` lo resetea. Feature 4/4 completo.
- 2026-10-10: re-revisión 100% funcional pedida por el usuario (tras microcorte de red, equipo nunca caído): 6/6 containers Up, 0 non-up; páginas login 200, `/` 307, sources/opportunities 200; 14/14 endpoints 200 con UN solo login; dashboard 15457/1441/243; métricas 201/201, degraded 28, failing 4, pending 0; scheduler con barridos cada 30 min (due=0 correcto); disco 68%. Aclarar a futuro: dashboard `total_opportunities=15457` vs `opportunities` en DB=2896 (conteos distintos, verificar definición).

## Verification evidence
- `docker ps -a`: 6 containers convocaradar Up (api/worker/web 23h healthy, pg/minio/backup 3d).
- `curl -o /dev/null -w %{http_code}`: `/observatorio/login` 200, `POST .../auth/login {}` 422.
- `SELECT count`: users 1→2, sources 201/201 enabled (vía `docker exec api python`, sin secretos en comandos).
- `cut -d= -f1 .env`: sin `ADMIN_EMAIL/ADMIN_PW/POSTGRES_USER`.
- T1: `git log` server `cd5cd5a` sobre `5a6efb3`, `status` limpio, `ls docker-compose.prod.yml` ausente, web healthy + login 200.
- T2: `POST /observatorio/api/v1/auth/login` con credencial nueva → 200 (verificado server-side, solo código).
- T3: task `b1f90bda` `success` 201/201; `source_runs` ventana 40 min: 201 runs, `items_found=1906`, `items_created=24`, by-status success 172/degraded 25/failed 4 (timeouts individuales).
- T4: 14 endpoints `CODE:200` vía `/observatorio/api/v1/*` con Bearer; `/dashboard/summary` con 15457/1441; `/admin/metrics` con 201/201 + embeddings 100% + pending 0.

## Next step
- Feature completo 4/4. Nuevo feature `fuentes-todas-on` (T1 hecho) sigue en `odd/tasks/fuentes-todas-on.md`. Follow-ups sueltos: push rama server a origin, rotación de secretos al cierre.
