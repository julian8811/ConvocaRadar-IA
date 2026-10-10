# Deployment — ConvocaRadar IA

Guía canónica breve: qué se despliega dónde. El detalle paso a paso vive en los anexos; esta guía no lo duplica.

## Dónde se despliega qué

| Destino | Qué corre | Documento con el detalle |
|---------|-----------|--------------------------|
| Vercel (Hobby) | Frontend web (Next.js App Router) | Esta guía (§ Cloud) |
| Render (Web Service) | API (FastAPI + SQLAlchemy) | Esta guía (§ Cloud) |
| Neon (Free) | PostgreSQL + pgvector (base cloud) | Esta guía (§ Cloud) |
| Servidor universitario | Stack autónomo `docker-compose.server.yml`: web tras Nginx + api, postgres, minio, worker y backup en red interna | `docs/deploy-universidad.md` (anexo técnico) |
| Entrega a evaluadores | Clonar, configurar, levantar y verificar el stack sin ayuda | `docs/entrega-universidad.md` (anexo de entrega) |

Almacenamiento: Cloudflare R2 o sistema de archivos local (según entorno).

Otros documentos (solo mención, no se duplican aquí): `docs/restore-runbook.md` (restauración y drill), `docs/estructura-local-vs-servidor.md` (qué vive dónde y qué diverge entre local y servidor), `docs/security/secret-rotation.md` (rotación de secretos).

## Cloud (Vercel + Render)

Los despliegues corren vía GitHub Actions (`.github/workflows/deploy.yml`):

1. **CI** en push/PR a `main` — lint + test API + test web.
2. **Deploy** cuando CI pasa en `main`: redeploy de la API en Render + `vercel deploy --prod` del frontend.

## Servidor universitario

Ruta documentada en el anexo técnico `docs/deploy-universidad.md`: compose autónomo del servidor, preflight obligatorio (`scripts/check-secrets.sh`, `scripts/server-preflight.sh`), Nginx como proxy reverso, verificación funcional y backup/restore. Para la entrega evaluada paso a paso, ver `docs/entrega-universidad.md`.

Camino prod canónico: `docker-compose.server.yml` standalone (no extiende `docker-compose.yml`; solo `web` publica en localhost).

## Variables requeridas

| Variable | Descripción |
|----------|-------------|
| `DATABASE_URL` | Cadena de conexión PostgreSQL (Neon o compose) |
| `POSTGRES_PASSWORD` | Clave de Postgres (compose) |
| `MINIO_ROOT_PASSWORD` | Clave de MinIO (compose) |
| `JWT_SECRET` | Firma JWT (mín. 32 caracteres) |
| `INTERNAL_API_KEY` | Clave API interna (mín. 32 caracteres) |
| `RESET_TOKEN_SECRET` | Secreto de restablecimiento de clave (mín. 32 caracteres) |

Ver `.env.example` (todas las variables) y `.env.production.example` (producción cloud). Los valores del servidor se generan en el servidor según `docs/deploy-universidad.md` (§3).

Qué clave alimenta cada compose (dev vs server, por servicio): `docs/env-matrix.md`.

## Desarrollo local

```bash
# API + DB + Storage
docker compose up

# O API aislada
cd apps/api && pip install -e ".[dev]" && uvicorn app.main:app --reload
```
