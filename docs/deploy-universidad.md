# Deploy en servidor universitario — ConvocaRadar IA

Esta guía es la ruta oficial para la VM de la universidad. Producción usa
`docker-compose.server.yml`, un Compose **autónomo** que no hereda puertos ni
ajustes del entorno de desarrollo.

## Arquitectura de producción

```text
Internet
   │
   ▼
Nginx :80/:443
   │
   ▼
127.0.0.1:3001 ── web (Next.js)
                     │
                     └── /api/v1/* → api:8000
                                        │
                              ┌─────────┴─────────┐
                              ▼                   ▼
                         postgres:5432       minio:9000
                              ▲
                              │
                         worker / backup
```

Solo `web` publica un puerto en el host y está ligado a loopback. PostgreSQL,
MinIO, API, worker y backup permanecen accesibles únicamente en la red Docker.

## 1. Requisitos

- Ubuntu 22.04+.
- Docker Engine 24+ y Docker Compose v2.
- Git y Nginx.
- Recomendado: 4 vCPU, 8 GB RAM y 30 GB libres. Mínimo práctico: 2 vCPU / 4 GB.
- Puertos externos 80/443; SSH restringido por la infraestructura institucional.
- Subdominio institucional para TLS.

Comprobar antes de continuar:

```bash
docker --version
docker compose version
git --version
free -h
df -h /
```

## 2. Instalar el repositorio

La ubicación recomendada, para mantenerlo separado de CEITTO, es:

```bash
sudo mkdir -p /home/ubuntu/apps
sudo chown -R ubuntu:ubuntu /home/ubuntu/apps
cd /home/ubuntu/apps

git clone https://github.com/julian8811/ConvocaRadar-IA.git convocaradar
cd convocaradar
```

Antes del despliegue final, usar exclusivamente el commit/tag aprobado en
GitHub. No desplegar una rama de trabajo sin CI verde.

## 3. Crear el entorno de producción

```bash
cp .env.production.example .env
chmod 600 .env
nano .env
```

Generar secretos **en el servidor**, nunca en el repositorio ni en el chat:

```bash
openssl rand -base64 24   # POSTGRES_PASSWORD
openssl rand -base64 24   # MINIO_ROOT_PASSWORD
openssl rand -base64 48   # JWT_SECRET
openssl rand -base64 48   # INTERNAL_API_KEY
openssl rand -base64 48   # RESET_TOKEN_SECRET
```

Valores mínimos a sustituir en `.env`:

```ini
POSTGRES_PASSWORD=<secreto>
MINIO_ROOT_PASSWORD=<secreto>
JWT_SECRET=<secreto>
INTERNAL_API_KEY=<secreto>
RESET_TOKEN_SECRET=<secreto>

FRONTEND_URL=https://<SUBDOMINIO_INSTITUCIONAL>
BACKEND_URL=https://<SUBDOMINIO_INSTITUCIONAL>
NEXT_PUBLIC_API_URL=/api/v1
NEXT_PUBLIC_ENV=production
WEB_PORT=3001
```

Si se habilita correo, usar una cuenta institucional/de servicio y completar
SMTP o Resend. No almacenar una contraseña personal en Git.

## 4. Preflight obligatorio

```bash
cd /home/ubuntu/apps/convocaradar

bash scripts/check-secrets.sh

docker compose \
  -p convocaradar \
  --env-file .env \
  -f docker-compose.server.yml \
  config >/tmp/convocaradar-server-config.yml

grep -nE '5434|9004|9005|8002' /tmp/convocaradar-server-config.yml && \
  echo 'ERROR: se encontró un puerto interno publicado' || true
```

El Compose de servidor debe publicar únicamente `127.0.0.1:3001 -> 3000` para
el servicio `web`.

## 5. Build y arranque

```bash
cd /home/ubuntu/apps/convocaradar

COMPOSE='docker compose -p convocaradar --env-file .env -f docker-compose.server.yml'

$COMPOSE build --pull
$COMPOSE up -d postgres minio
$COMPOSE up -d api
$COMPOSE up -d worker backup web
$COMPOSE ps
```

No se ejecuta una migración manual adicional: el contenedor `api` ejecuta
`alembic upgrade head` antes de iniciar Uvicorn. Worker y web esperan a que API
esté saludable.

Comprobar desde la VM:

```bash
curl -fsS http://127.0.0.1:3001/ >/dev/null && echo 'WEB OK'
curl -fsS http://127.0.0.1:3001/api/v1/health/live && echo

docker compose -p convocaradar --env-file .env -f docker-compose.server.yml ps
```

## 6. Nginx

Como `/api/v1` lo resuelve internamente Next.js, Nginx solo necesita un
upstream en loopback:

```nginx
server {
    listen 80;
    server_name <SUBDOMINIO_INSTITUCIONAL>;

    client_max_body_size 12m;

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Validar antes de recargar:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

TLS debe instalarse con el mecanismo autorizado por la universidad (certificado
institucional o Certbot si la infraestructura lo permite).

## 7. Verificación funcional

Después de Nginx/TLS:

```bash
curl -fsS https://<SUBDOMINIO_INSTITUCIONAL>/api/v1/health/live && echo
```

Además comprobar manualmente:

1. Carga de la página y login.
2. Listado y detalle de convocatorias.
3. Fuentes y última actualización.
4. Ejecución del worker sin reinicios continuos.
5. Subida/lectura de un documento en MinIO si esa función está habilitada.
6. Flujo de correo/restablecimiento solo si SMTP/Resend está configurado.

Logs útiles sin mostrar secretos:

```bash
COMPOSE='docker compose -p convocaradar --env-file .env -f docker-compose.server.yml'
$COMPOSE logs --tail=100 api
$COMPOSE logs --tail=100 worker
$COMPOSE logs --tail=100 web
```

## 8. Backups

El contenedor `backup` incluye `pg_dump` 16 y Supercronic dentro de la imagen;
no descarga ejecutables cada vez que inicia. Ejecuta el ciclo diario definido en
`scripts/crontab-backup` y conserva por defecto 14 días.

Backup manual antes de cada actualización:

```bash
COMPOSE='docker compose -p convocaradar --env-file .env -f docker-compose.server.yml'
$COMPOSE exec backup /scripts/backup-cycle.sh
$COMPOSE logs --tail=50 backup
```

No actualizar producción si el backup manual no termina con `PASS`.
Restauración: `docs/restore-runbook.md`.

## 9. Actualización segura

Antes de actualizar, registrar el commit activo y crear backup:

```bash
cd /home/ubuntu/apps/convocaradar
git rev-parse HEAD
COMPOSE='docker compose -p convocaradar --env-file .env -f docker-compose.server.yml'
$COMPOSE exec backup /scripts/backup-cycle.sh
```

Luego:

```bash
git fetch --tags origin
git checkout <TAG_O_COMMIT_APROBADO>
$COMPOSE build --pull api worker web backup
$COMPOSE up -d api
$COMPOSE up -d worker backup web
$COMPOSE ps
curl -fsS http://127.0.0.1:3001/api/v1/health/live && echo
```

Si el nuevo contenedor no queda saludable, volver al commit anterior y
reconstruir la aplicación. Si la migración cambió datos/esquema de forma no
compatible, seguir el runbook de restauración en vez de improvisar un downgrade.

## 10. Checklist de entrega

- [ ] CI del commit/tag aprobado completamente verde.
- [ ] `.env` con permisos `600` y sin placeholders.
- [ ] Solo `127.0.0.1:3001` publicado por el stack.
- [ ] PostgreSQL, MinIO y API sin puertos del host.
- [ ] Todos los contenedores `running`; los que tienen healthcheck, `healthy`.
- [ ] Web y `/api/v1/health/live` responden desde loopback.
- [ ] Nginx `nginx -t` correcto y TLS operativo.
- [ ] Login y flujo principal verificados.
- [ ] Worker estable y sin bucle de reinicio.
- [ ] Backup manual termina en `PASS`.
- [ ] Restauración documentada y backup conservado antes de cada release.
- [ ] Commit/tag de producción registrado para rollback.
