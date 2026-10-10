# Higiene y estructura del repo + local vs servidor — feature ODD

## Objective
Dejar ConvocaRadar-IA ordenado con buenas prácticas (raíz legible, scripts indexados, docs canónicas, un solo camino prod documentado) y dejar por escrito la estructura local vs servidor universitario sin tocar el servidor hasta tener autorización remota explícita.

## Problem
1. Raíz con artefactos locales (`node_modules/`, `.pytest_cache/`, `.ruff_cache/` en disco), `CNAME` huérfano y `scripts/__pycache__/*.pyc` sin índice (mapa explorer 2026-10-10).
2. `scripts/` (~28 ficheros) mezcla scraper/backfill/fuentes/backup/deploy sin `README`; `apps/api/scripts/` (5) duplica propósito; `apps/backup/` es solo un `Dockerfile`.
3. Docs de despliegue triplicados (`DEPLOYMENT.md`, `docs/deploy-universidad.md`, `docs/entrega-universidad.md`) + `docs/scraper.md` (ciclo "021") probablemente desactualizado frente a tests `023/026-040`.
4. Triple compose con dos caminos prod que compiten (`docker-compose.server.yml` standalone vs `docker-compose.prod.yml` overlay) + doble `pnpm-workspace.yaml` + `apps/web/.gitignore` redundante.
5. Divergencia local-vs-servidor solo registrada dentro de `odd/tasks/convocaradar-runall-abort.md:28` (rama `server/observatorio-production-prebasepath-20260909` en 10.3.1.128); sin doc dedicado ni verificación remota autorizada.

## Why
Sin esto cada cambio paga impuesto de orientación, el deploy universitario vive de memoria tribal y cualquier "orden" improvisado puede tumbar prod (Render/Vercel/server). Verificado en mapa read-only (solo lectura, sin índices CodeGraph).

## Scope
- IN (local, seguro): limpieza raíz sin borrar código, `scripts/README.md`, fusión de docs deploy en una guía canónica + anexos, alinear templates `.env`, plegar gitignores, documentar doble workspace pnpm, archivar/actualizar `scraper.md`, doc dedicado `docs/estructura-local-vs-servidor.md` (con sección servidor marcada PENDIENTE hasta autorización).
- OUT (requiere decisión/autorización): cambiar el camino prod (standalone vs overlay), tocar `render.yaml`/`deploy.yml`/secretos, migraciones, scripts de backup, `CNAME`/`vercel.json`/bundle web, `CODEOWNERS`/`settings.yml`, y CUALQUIER operación en 10.3.1.128 (inspección, rebuild, clic e2e).
- Rama server + rebuild + e2e: fuera de este slice hasta autorización remota explícita (destino, operación, credencial).

## Constraints
- Conventional Commits, sin atribución IA. Rama feature desde `main` (limpio y en sync con `origin/main` en `eff02d8` tras push/fetch 2026-10-10). Push/PR/merge los decide el usuario.
- TDD strict (convención del repo): API `cd apps/api && pytest tests/` (focado por tarea, completa al cierre); web `npm run test` (vitest) + `tsc --noEmit` donde aplique. Higiene/docs sin RED ejecutable: excepción documentada + checks estructurales/estáticos.
- RDD ON (global): writer corre `## Verification` en foreground y reporta `comando: resultado`; review nativa como chequeo independiente por work-unit commit.
- Delivery `ask-on-risk`, heurística ~400 líneas solo orientativa (los docs pueden superarla con explicación breve, sin rework cosmético).
- Secreto del chat (PAT) NO se guarda en repo, memoria ni config; origin sigue en HTTPS plano; rotar el token tras su uso one-shot.

## Tasks
- [x] **T1 (P0 local, seguro)** ✅ commit `d3e7544` (writer delegado: verificación + doc; padre: `rm -rf scripts/__pycache__` con 3 `.pyc` ignorados/no trackeados + `git rm apps/web/.gitignore` con redundancia 7/7 verificada). `CNAME`: NO tocado, decisión dejada al usuario. Ruta: delegada + cierre padre.
- [x] **T2 (P0 local)** ✅ commit `5605529` (`scripts/README.md`: tabla propósito/uso de los 29 scripts de `scripts/` + 5 de `apps/api/scripts/` en 4 grupos — scraper/backfill, fuentes, deploy/backup, infra; comandos ejemplo solo donde el encabezado los documenta, resto "ver encabezado", cero secretos). Cobertura 34/34 verificada en disco (`ls scripts/` + `ls apps/api/scripts/`, 2026-10-10). Ruta: delegada.
- [x] **T3 (P1 local)** ✅ commit `c6878cf` (docs deploy canónicas: `DEPLOYMENT.md` guía breve con tabla destino→anexo, detalle movido a anexos; cross-refs en los tres + mención a `estructura-local-vs-servidor.md`; `README.md` sin tocar — sin links a estos docs; `scraper.md` vigente + 2 líneas de estado con evidencia de tests). Cierre `chore(odd)`: este commit. Ruta: delegada. Checks: grep de referencias, `check-secrets.sh`, `git diff --stat`.
- [x] **T4 (P1, con decisión)** ✅ commit `c0f0718` (decisión del usuario: standalone canónico; `git rm docker-compose.prod.yml`; test renombrado a `test_prod_server_standalone.py` con asserts sobre `server.yml` — aislamiento solo-web-en-localhost, `BOOTSTRAP_SOURCES_ON_STARTUP=false`, `S3_*`, backup por build; `DEPLOYMENT.md` + `estructura-local-vs-servidor.md` declaran el standalone; `ci.yml` sin tocar — ya validaba `server.yml` y no citaba el test por nombre). Ruta: delegada.
- [x] **T5 (P1 local)** ✅ commit `4a764f8` (`docs/env-matrix.md` nuevo, 15 filas: 5/5 `${VAR}` del compose dev + 15/15 del server cubiertos, qué-clave→qué-compose→qué-servicio + `env_file` de api/worker; `DEPLOYMENT.md` +2 líneas con puntero — la tabla excedía el presupuesto de ~40 líneas). Cero renombres: 5 discrepancias documentadas con prueba grep (puente `S3_*`←`MINIO_*` con lectores en código/CI/scripts/docs; `BACKUP_RETENTION_DAYS` ausente en `.env.example`; `RESEND_FROM` duplicado en `.env.example`; `POSTGRES_DATABASE_URL` y `OPENAI_API_KEY` sin consumidor en código). Cierre `chore(odd)`: este commit. Ruta: delegada. Checks: conteo de claves por template vs filas, `check-secrets.sh`, `git diff --stat`.
- [ ] **T6 (P2 local)** `apps/backup/` + workspaces: documentar/consolidar `apps/backup/Dockerfile` con su lógica real y resolver doble `pnpm-workspace.yaml`. Ruta: delegada. Checks: `pnpm -r exec true` o equivalente no destructivo + hadolint del Dockerfile.
- [ ] **T7 (P2 local)** CI higiene propuesta (sin aplicar): dummy secrets vía `env:` en vez de `sed -i`, frozen lockfile en Vercel, plan ratchet ruff. Ruta: delegada (propuesta). Checks: `yamllint`/revisión + CI verde en rama.
- [x] **T8-doc (P1)** ✅ commit `4579416` con `docs/estructura-local-vs-servidor.md` (45 líneas, estructura local + servidor + divergencias + pendientes, cero secretos). Inspección remota hecha 2026-10-10 en solo lectura. Credencial NO persistida; rotación recomendada.

## Acceptance
- `git status` limpio de artefactos; `scripts/README.md` cubre el 100% de scripts raíz; una sola guía deploy canónica referenciada desde `README.md`.
- `docs/estructura-local-vs-servidor.md` existe con local verificado y servidor pendiente/autorizado según corresponda.
- Ningún secreto en repo (`check-secrets.sh` verde); origin sin token persistido; PAT rotado por el usuario.
- Suites afectadas verdes o excepción documentada por tarea; cada tarea cierra con work-unit commit en rama feature y su identidad registrada aquí.

## Progress
- 2026-10-10: doc creado en `odd/tasks/repo-higiene-estructura.md` (8 tareas). Mapa read-only delegado (explorer, ~2k tokens, 15 puntos accionables). `main` en sync con `origin/main` (`eff02d8`, fetch confirma remote = local). PAT usado one-shot vía URL explícita sin mutar `origin`; pendiente rotación por el usuario. Mirror Engram pendiente (sesiones runtime múltiples, reintentar con sesión autoritativa).
- 2026-10-10: T1+T8-doc ejecutados en `feature/repo-higiene-estructura` (writer `partial`: verificación + doc, sin comandos mutantes; padre cerró terminal). Commits `d3e7544` (chore) + `4579416` (docs). `check-secrets.sh` exit 0; spot-check padre `git status` + lectura del doc OK.
- 2026-10-10: push `feature/repo-higiene-estructura` a `origin` verificado (remote = `f293cae`, 5 commits sobre `main`); PAT usado one-shot vía URL explícita sin mutar `origin`. PR #35 creado por el padre (título `chore(repo): higiene raiz + mapa local-vs-servidor (T1, T8)`, base `main`, label `type:chore`, body según template del repo; nota honesta: sin issue linkeada porque el repo no usa ese flujo — rama `feature/` sigue la convención propia del repo como `feature/convocaradar-runall-abort`).

## Verification evidence
- Mapa: handoff explorer (15 evidencias path:línea) + spot-check padre (`ls`, compose/docs/scripts listados).
- Sync: `git fetch origin main` → `main...origin/main` sin ahead/behind; `ls-remote main` = `eff02d8`.
- Servidor 10.3.1.128 (2026-10-10, solo lectura vía SSH, sin valores de secretos — solo nombres de claves):
  - Repo en `/srv/apps/convocaradar` (symlink `~/apps/convocaradar`), rama `server/observatorio-production-prebasepath-20260909`, HEAD `5a6efb3` (lexbor), apilado sobre `fc64fde`, `7c79b2a`, `86bd42b`, `d7c91ae`; `status` limpio.
  - Divergencia vs local: al server le faltan `cd0ea27` (fix `isAbortError` DOM) y `8119f7a` (doc T4) — port pendiente.
  - Compose: `docker-compose.server.yml` (6.4K, 25-sep) + `docker-compose.yml` + `docker-compose.prod.yml`; `.env` real presente (600, 3.2K, 12-sep) + ambos templates.
  - `docker ps`: SOLO `convocaradar-web-1` Up 22h (healthy) — api/worker/db no visibles; verificar causa antes de cualquier e2e.
  - Backups: symlinks `~/convocaradar-backups-20260909-031328`, `~/convocaradar-users-*.sql` → `/srv/backups/convocaradar/`.

## Forecast / delivery
- Forecast: ~6-10 ficheros docs + 2-4 normalizaciones config por tarea; total estimado supera ~400 líneas autoradas → estrategia `ask-on-risk`: slices por tarea (T1-T2 slice 1, T3+T8-esqueleto slice 2, resto propuesta), un PR por slice salvo que el usuario pida cadena apilada.
- Boundaries y PRs: registrar aquí por tarea (commit, slice, PR).

## Next step
- T2 `scripts/README.md` (writer acotado) tras visto bueno del usuario; T4 requiere decisión standalone-vs-overlay; server: verificar api/worker/db + portar `cd0ea27`/`8119f7a` (nueva autorización para writes remotos). Push/PR de esta rama los decide el usuario.
- 2026-10-10: T3 ejecutada en `feature/repo-higiene-t3` (desde `main` `13730fc`, limpio y en sync con `origin/main`). Commit docs `c6878cf`. Hallazgos: (1) `DEPLOYMENT.md` describía el servidor vía overlay `docker-compose.prod.yml` (puerto 8002), contradicho por ambos anexos (`server.yml` standalone, puerto 3001) — corregido a puntero al anexo + nota T4 pendiente, sin decidir el camino prod; (2) `scraper.md` vigente (veredicto + evidencia en el doc); (3) `docs/estructura-local-vs-servidor.md:44` conserva el pendiente de scraper sin marcar — ese archivo no era superficie editable de T3.
- 2026-10-10: T4 ejecutada en `feature/repo-higiene-t4` (desde `main` `bf2e649`, limpio y en sync con `origin/main`). Commit impl `c0f0718`. Baseline overlay: 30 passed + 1 failed (`test_deployment_md_references_prod`, `DEPLOYMENT.md` T3 ya no documentaba health URLs) → RED intermedio genuino (`test_deployment_md_declares_server_standalone` detectó mención residual del overlay en la línea nueva) → GREEN final 40/40 + suite `-k "compose or prod or overlay or server"` 59/59; `ruff check` limpio; `docker compose config` no ejecutable (docker no disponible en el entorno). Residuales fuera de superficie: historial del feature doc (líneas 10/55/65) y registro del servidor (`estructura-local-vs-servidor.md:28`, el host conserva el fichero hasta limpieza remota autorizada).
