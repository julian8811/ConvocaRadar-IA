# Estructura local vs servidor

Comparación verificada entre el repo local (`main`) y el servidor de producción. Fecha de relevamiento: 2026-10-10.

> Detalle de despliegue: ver `DEPLOYMENT.md` (guía general) y `docs/deploy-universidad.md` (despliegue universitario). Este documento no los duplica: solo ubica qué vive dónde y qué diverge.

## Estructura local verificada (`main` en `eff02d8`, en sync con `origin/main`)

Raíz: `README.md`, `DEPLOYMENT.md`, `CONTRIBUTING.md`, `VERSIONING.md`, `CHANGELOG.md`, `Makefile`, `package.json` (scripts `test:api` / `test:web` / `dev:api`), `pnpm-workspace.yaml` + `pnpm-lock.yaml`, `CNAME` (trackeado, apunta a `convocaradar-web.vercel.app`), `render.yaml`, `vercel.json`.

| Área | Contenido verificado |
|------|----------------------|
| `apps/api/` | FastAPI; `pytest` con `asyncio_mode=auto`; `ruff` mínimo (`E9,F63,F7,F82`); `alembic.ini`; `Dockerfile` + `.dockerignore`; `apps/api/scripts/` con 5 ficheros (`backfill_022.py`, `bench_golden.py`, `probe_funding_candidates.py`, `re_scrape_detail.py`, `tune_thresholds.py`) |
| `apps/web/` | Next 16 + React 19; `vitest` con `happy-dom`; `eslint` (`next/core-web-vitals`); doble `pnpm-workspace.yaml`; `.gitignore` propio redundante con el de raíz (pendiente `git rm`, ver T1) |
| `apps/backup/` | Solo `Dockerfile`; la lógica vive en `scripts/backup-*` |
| `scripts/` | ~30 ficheros (`.py` / `.sh` / `.mjs`), sin `README`. Incluye `check-secrets.sh`, `server-preflight.sh`, `trigger-render-deploy.sh`, `verify_latest_backup.sh`, `crontab-backup` y la familia `backup-cycle.sh` / `backup-loop.sh` / `backup_offsite.py` |
| `docs/` | `deploy-universidad.md`, `entrega-universidad.md`, `restore-runbook.md`, `scraper.md` (describe el ciclo "021", probablemente desactualizado), `secret-rotation.md`, `security/` |
| Compose | `docker-compose.yml` (dev: puertos 5434/9004-5/8002/3002), `docker-compose.server.yml` (prod standalone, web en `127.0.0.1:3001`), `docker-compose.prod.yml` (overlay) |
| `.github/` + CI | `ci.yml` (8 jobs), `deploy.yml` (Render `srv-d938h6m7r5hc73bo7u00` + Vercel + healthcheck), además `health-check.yml`, `keep-alive.yml`, `release.yml` |

## Servidor (datos provistos, sin re-inspección remota)

Host `10.3.1.128`. Repo en `/srv/apps/convocaradar` (symlink desde `~/apps/convocaradar`).

| Aspecto | Estado |
|---------|--------|
| Rama / HEAD | `server/observatorio-production-prebasepath-20260909`, HEAD `5a6efb3` (lexbor) sobre `fc64fde`, `7c79b2a`, `86bd42b`, `d7c91ae`; working tree limpio |
| Compose | `docker-compose.server.yml` (6.4K) + dev + prod presentes |
| Env | `.env` real (modo `600`) + ambas plantillas (`.env.example`, `.env.production.example`); solo se referencian nombres de fichero, ningún valor |
| `docker ps` | SOLO `convocaradar-web-1` Up 22h healthy; `api` / `worker` / `db` no visibles |
| Backups | En `/srv/backups/convocaradar/` |

## Divergencias local vs servidor

- Al servidor le faltan 2 commits de `main`: `cd0ea27` (fix `isAbortError` DOM) y `8119f7a` (doc T4). El servidor NO está en `main`: sigue su rama `server/...` con HEAD `5a6efb3`.
- `CNAME` existe y está trackeado en local; su vigencia en el flujo Vercel actual está sin decidir (borrar vs documentar).
- `apps/web/.gitignore` es 100 % redundante con `.gitignore:40-52`; pendiente eliminarlo en local (T1).

## Qué falta verificar

- [ ] Estado real de `api` / `worker` / `db` en el servidor (caídos vs nunca desplegados en este host).
- [ ] Porte de `cd0ea27` y `8119f7a` a la rama del servidor (o decisión de no portar).
- [ ] Decisión `CNAME`: borrar vs documentar su propósito.
- [ ] `docs/scraper.md`: confirmar si el ciclo "021" sigue vigente o actualizarlo.
- [ ] Secretos: solo nombres de claves en plantillas; rotación según `docs/secret-rotation.md` (ver `security/`).
