# Matriz de entorno: qué clave alimenta cada compose

Dev (`docker-compose.yml`) se alimenta de `.env` (plantilla `.env.example`).
Server (`docker-compose.server.yml`, standalone, no hereda del dev) se alimenta
de `.env` (plantilla `.env.production.example`). Solo NOMBRES de claves, jamás valores.

## Clave → compose → servicio

| Clave | `docker-compose.yml` (dev) | `docker-compose.server.yml` (server) |
|-------|----------------------------|--------------------------------------|
| `POSTGRES_PASSWORD` | postgres, api, worker (`DATABASE_URL` inline), backup | postgres, api, worker (`DATABASE_URL` inline), backup |
| `MINIO_ROOT_PASSWORD` | minio | minio, api, worker, backup (vía `S3_SECRET_KEY`) |
| `MINIO_ROOT_USER` | — (fijo `minio` en el compose) | minio, api, worker, backup (vía `S3_ACCESS_KEY`) |
| `INTERNAL_API_KEY` | api, worker | api, worker |
| `WEB_PORT` | web (defecto 3002) | web (defecto 3001, solo localhost) |
| `BACKUP_RETENTION_DAYS` | backup (defecto 14) | backup (defecto 14) |
| `S3_ENDPOINT_URL` | — (fijo `http://minio:9000` en api/worker) | api, worker, backup (con defecto propio en backup) |
| `S3_BUCKET` | — | api, worker, backup |
| `S3_REGION` | — | api, worker, backup |
| `BACKUP_S3_ENABLED` | — | backup |
| `BACKUP_S3_BUCKET` | — | backup |
| `BACKUP_S3_PREFIX` | — | backup |
| `BACKUP_S3_RETENTION_DAYS` | — | backup |
| `NEXT_PUBLIC_API_URL` | — (fijo `http://localhost:8002/api/v1` en build) | web (build arg, defecto `/api/v1`) |
| `NEXT_PUBLIC_ENABLE_WAKE_RETRIES` | — | web (build arg, defecto `true`) |

Cobertura: 5/5 `${VAR}` del compose dev y 15/15 del compose server están en la tabla.
Además, `api` y `worker` cargan el `.env` completo vía `env_file` en ambos composes
(claves runtime de la app: `DATABASE_URL`, `JWT_SECRET`, `LLM_*`, `SCRAPING_*`, etc.).
`NEXT_PUBLIC_ENV=production` en el server es literal del compose, no variable.

## Discrepancias (documentadas, NO renombradas)

1. `S3_ACCESS_KEY` / `S3_SECRET_KEY` se alimentan de `MINIO_ROOT_USER` /
   `MINIO_ROOT_PASSWORD` en el server. Es un puente intencional (el código lee `S3_*`:
   `scripts/backup_offsite.py`, tests y CI los citan); renombrar tocaría código, CI,
   scripts, docs y servidor: NO se renombra.
2. `BACKUP_RETENTION_DAYS` la usan ambos composes y `scripts/backup-*.sh`, pero falta
   en `.env.example` (sí está en `.env.production.example`).
3. `.env.example` trae `RESEND_FROM` dos veces (línea duplicada).
4. `POSTGRES_DATABASE_URL` solo existe en `.env.example`, sin consumidor en código ni
   composes (el compose construye `DATABASE_URL` inline desde `POSTGRES_PASSWORD`).
5. `OPENAI_API_KEY` solo existe en `.env.production.example`, sin lector en el código
   (el gateway lee `GEMINI_API_KEY` + alias `LLM_API_KEY`); `LLM_API_KEY` a su vez solo
   está en `.env.example`. Definir la llave por proveedor requiere decisión de producto.
