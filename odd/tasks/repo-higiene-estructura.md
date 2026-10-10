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
- [ ] **T2 (P0 local)** `scripts/README.md` + orden sin mover código: tabla propósito/uso de los ~28 scripts + los 5 de `apps/api/scripts/`, o subdirs propuestos sin ejecutar el move. Ruta: delegada. Checks: estructurales (tabla cubre todos los ficheros) + `bash -n` en tocados si hay sh.
- [ ] **T3 (P1 local)** Docs deploy canónicas: fusionar `DEPLOYMENT.md` + 2 docs universidad en una guía + anexos, resolver vigencia de `docs/scraper.md` (actualizar o archivar). Ruta: delegada. Checks: sin links rotos (grep de referencias), CI docs si existe.
- [ ] **T4 (P1, con decisión)** Un solo camino prod documentado: proponer standalone vs overlay (evidencia `docker-compose.*`, `Makefile:7`, `ci.yml`), sin cambiar runtime hasta que el usuario elija. Ruta: delegada (propuesta, sin mutar compose). Checks: `docker compose config` de ambos caminos en dry-run.
- [ ] **T5 (P1 local)** Templates env alineados: tabla qué clave alimenta cada compose (dev vs server), sin tocar secretos reales. Ruta: inline o delegada según tamaño. Checks: `grep` de claves + `docker compose config`.
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
- 2026-10-10: CNAME borrado en `cfad978` por decisión del usuario (resto inerte de `051e200`, sin efecto en Vercel/Render/Pages); docs actualizados. Push de la rama pendiente de credencial.

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
