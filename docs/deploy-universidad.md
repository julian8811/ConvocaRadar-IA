# Deploy en Servidor Universitario — ConvocaRadar IA

Guía self-hosted con Docker Compose. El stack ya está listo: `docker-compose.yml`
levanta **postgres + pgvector, minio, api, worker, backup y web**.

## 1. Requisitos del servidor

- Ubuntu 22.04+ o similar (VM de la universidad)
- Docker Engine ≥ 24 + Compose v2 (`docker compose version`)
- 2 vCPU / 4 GB RAM mínimo, 20 GB disco
- Puertos 80/443 abiertos (o el que asigne la universidad) + acceso SSH
- Dominio o subdominio (ej: `convocaradar.universidad.edu.co`) — opcional pero recomendado

## 2. Preparar el repo en el servidor

```bash
git clone https://github.com/julian8811/ConvocaRadar-IA.git
cd ConvocaRadar-IA

cp .env.example .env
# Editar .env — ver sección 3 (todos los valores change-me deben cambiarse)
nano .env
```

> `.env` nunca se commitea. Está en `.gitignore`. Usá `.env.example` y
> `.env.production.example` como plantillas.

## 3. Variables mínimas (producción universitaria)

En `.env` completar **al menos**:

```ini
POSTGRES_PASSWORD=<generar con: openssl rand -base64 24>
MINIO_ROOT_PASSWORD=<generar con: openssl rand -base64 24>
JWT_SECRET=<openssl rand -base64 48>
INTERNAL_API_KEY=<openssl rand -base64 48>
RESET_TOKEN_SECRET=<openssl rand -base64 48>

# URLs públicas (ajustar al dominio real)
FRONTEND_URL=https://convocaradar.universidad.edu.co
BACKEND_URL=https://convocaradar.universidad.edu.co
NEXT_PUBLIC_API_URL=https://convocaradar.universidad.edu.co/api/v1
```

Opcionales pero recomendados:

```ini
SENTRY_DSN=https://...@sentry.io/...
LLM_PROVIDER=cloudflare  # o local / openai según credenciales
# Si LLM_PROVIDER != local:
LLM_API_KEY=...
# Email (Resend o SMTP universidad/Outlook):
RESEND_API_KEY=...
# o SMTP_HOST/SMTP_USER/SMTP_PASSWORD si usan servidor de correo interno
```

Validación: `bash scripts/check-secrets.sh` debe pasar sin errores antes de levantar.

## 4. Levantar el stack

```bash
# Build + up (usa el Dockerfile de api y web, contexto = raíz del repo)
docker compose build --pull
docker compose up -d postgres minio
sleep 10
docker compose up -d api worker web backup

# Ver estado
docker compose ps
docker compose logs -f --tail=100 api
curl -fsS http://localhost:8002/api/v1/health/live && echo "API OK"
curl -fsS http://localhost:3002/ | head
```

URLs por defecto:
- API: `http://<servidor>:8002` → `/api/v1/health/live`
- Web: `http://<servidor>:3002`
- MinIO consola: `http://<servidor>:9005`

## 5. Reverse proxy + TLS (recomendado)

No exponer los puertos 8002/3002 directamente. Usar Nginx/Caddy/Traefik delante:

**Ejemplo Nginx** (ajustar `server_name`):

```nginx
server {
    listen 80;
    server_name convocaradar.universidad.edu.co;
    location /api/ { proxy_pass http://127.0.0.1:8002; }
    location / { proxy_pass http://127.0.0.1:3002; }
}
# Luego: certbot --nginx -d convocaradar.universidad.edu.co
```

Alternativa simple: `caddy reverse-proxy --from convocaradar.universidad.edu.co --to localhost:3002`

## 6. Crear usuario admin

```bash
docker compose exec api convocaradar-seed-admin \
  --email admin@universidad.edu.co \
  --password-env INTERNAL_API_KEY
# O con password directo (cambiar luego):
# docker compose exec api python -m app.db.seed_admin --email admin@... --password '...'
```

## 7. Backups

El servicio `backup` ya está configurado (pg_dump 03:30 UTC diario, retención 14 días):

```bash
docker compose logs backup
docker compose exec backup /scripts/backup-cycle.sh   # manual
ls -lh $(docker volume inspect convocaradar_backups-data --format '{{.Mountpoint}}')
```

Restore: ver `docs/restore-runbook.md` (paso a paso con scratch DB).

## 8. Actualizar (deploy de nueva versión)

```bash
git pull origin main
docker compose build api web
docker compose up -d api worker web
docker compose exec api alembic upgrade head
docker compose ps
curl -fsS http://localhost:8002/api/v1/health/live
```

Para la rama de desarrollo actual:

```bash
git fetch origin
git checkout 023-scraper-funding-p95
git pull
# mismo build/up
```

## 9. Qué NO subir al servidor

- `.env` (generar en el servidor)
- `convocaradar.db` / `*.db` (solo dev local)
- `node_modules/`, `.next/`, `.venv/`, `.coverage`
- `backups/*.sql.gz` (se generan en el servidor)

Todo eso ya está en `.gitignore`.

## 10. Checklist antes de entregar

- [ ] `bash scripts/check-secrets.sh` sin hallazgos
- [ ] `.env` con 5 secretos ≥32 chars y URLs reales
- [ ] `docker compose ps` — 6 servicios healthy/running
- [ ] `curl /api/v1/health/live` OK y `/` de web responde
- [ ] Login admin funciona, fuentes se listan (93 seeds)
- [ ] Backup manual OK (`backup-cycle.sh` → PASS)
- [ ] Dominio + TLS funcionando (si aplica)
- [ ] `CONTRIBUTING.md` y `DEPLOYMENT.md` al día
```
