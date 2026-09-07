# Deploy en servidor universitario — ConvocaRadar IA

Esta guía es la ruta oficial para la VM universitaria. Producción usa `docker-compose.server.yml`, un Compose autónomo que no hereda puertos ni ajustes del entorno de desarrollo.

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

Solo `web` publica un puerto en el host y está ligado a loopback. PostgreSQL, MinIO, API, worker y backup permanecen accesibles únicamente en la red Docker.

## 1. Requisitos y diagnóstico inicial de la VM

Requisitos:

- Ubuntu 22.04+.
- Docker Engine 24+ y Docker Compose v2.
- Git y Nginx.
- Recomendado: 4 vCPU, 8 GB RAM y 30 GB libres. Mínimo práctico: 2 vCPU / 4 GB.
- Puertos externos 80/443; SSH restringido por la infraestructura institucional.
- Subdominio institucional para TLS.

Antes de crear directorios, clonar el repositorio o modificar Nginx, ejecutar únicamente comprobaciones de lectura:

```bash
set -u
printf '%s\n' '=== OS ==='
cat /etc/os-release
uname -a

printf '%s\n' '=== RESOURCES ==='
free -h
df -h /

printf '%s\n' '=== TOOLS ==='
docker --version || true
docker compose version || true
git --version || true
nginx -v 2>&1 || true

printf '%s\n' '=== DOCKER ACCESS ==='
docker info >/dev/null 2>&1 && echo 'DOCKER_DAEMON=OK' || echo 'DOCKER_DAEMON=UNAVAILABLE'

printf '%s\n' '=== PORTS ==='
ss -ltnp 2>/dev/null | grep -E ':(80|443|3001)\b' || true

printf '%s\n' '=== EXISTING CONVOCARADAR ==='
test -e /home/ubuntu/apps/convocaradar && ls -ld /home/ubuntu/apps/convocaradar || echo 'CONVOCARADAR_PATH=ABSENT'
docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null | grep -i convocaradar || true
```

No continúes si la VM tiene recursos insuficientes, Docker no está disponible o `3001` pertenece a un servicio ajeno a ConvocaRadar.

## 2. Instalar el repositorio

La ubicación oficial es:

```bash
sudo mkdir -p /home/ubuntu/apps
sudo chown ubuntu:ubuntu /home/ubuntu/apps
cd /home/ubuntu/apps

git clone https://github.com/julian8811/ConvocaRadar-IA.git convocaradar
cd convocaradar
```

Antes del despliegue final, usar exclusivamente el commit o tag aprobado en GitHub. No desplegar una rama de trabajo.

Registrar el SHA seleccionado:

```bash
git rev-parse HEAD
git status --short
```

El árbol debe estar limpio.

## 3. Crear el entorno de producción

```bash
cp .env.production.example .env
chmod 600 .env
nano .env
```

Genera los secretos **en el servidor**, nunca en el repositorio ni en el chat:

```bash
openssl rand -base64 24   # POSTGRES_PASSWORD
openssl rand -base64 24   # MINIO_ROOT_PASSWORD
openssl rand -base64 48   # JWT_SECRET
openssl rand -base64 48   # INTERNAL_API_KEY
openssl rand -base64 48   # RESET_TOKEN_SECRET
```

Valores mínimos a sustituir:

```ini
POSTGRES_PASSWORD=<secreto>
MINIO_ROOT_PASSWORD=<secreto>
S3_SECRET_KEY=<mismo valor de MINIO_ROOT_PASSWORD>
JWT_SECRET=<secreto>
INTERNAL_API_KEY=<secreto>
RESET_TOKEN_SECRET=<secreto>

FRONTEND_URL=https://<SUBDOMINIO_INSTITUCIONAL>
BACKEND_URL=https://<SUBDOMINIO_INSTITUCIONAL>
NEXT_PUBLIC_API_URL=/api/v1
NEXT_PUBLIC_ENV=production
WEB_PORT=3001
```

`DATABASE_URL` debe usar la misma contraseña PostgreSQL y el host interno `postgres:5432`.

Si se habilita correo, usa una cuenta institucional/de servicio y completa SMTP o Resend. No almacenes contraseñas personales en Git.

## 4. Preflight obligatorio y seguro

No guardes la salida expandida de `docker compose config` en archivos temporales: puede contener variables sensibles.

Desde el checkout de producción ejecuta el preflight oficial:

```bash
cd /home/ubuntu/apps/convocaradar
bash scripts/check-secrets.sh
EXPECTED_WEB_PORT=3001 bash scripts/server-preflight.sh
```

El resultado válido termina con:

```text
PREFLIGHT=PASS
```

El script comprueba, sin imprimir secretos:

- Docker y Compose disponibles;
- `.env` con permisos restringidos;
- secretos mínimos presentes y sin placeholders;
- URLs públicas configuradas;
- puerto 3001 sin colisión ajena;
- Compose de servidor renderizable;
- PostgreSQL, MinIO, API, worker y backup sin puertos de host;
- web publicado exclusivamente como `127.0.0.1:3001 -> 3000`;
- servicios de aplicación `read_only`, `cap_drop: ALL` y `no-new-privileges`;
- SHA de Git y limpieza de archivos rastreados.

No arranques producción si el preflight falla.

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

No ejecutes una migración manual adicional: el contenedor `api` ejecuta `alembic upgrade head` antes de iniciar Uvicorn. Worker y web esperan a que API esté saludable.

Comprobar desde la VM:

```bash
curl -fsS http://127.0.0.1:3001/ >/dev/null && echo 'WEB OK'
curl -fsS http://127.0.0.1:3001/api/v1/health/live && echo
$COMPOSE ps
```

Los servicios con healthcheck deben quedar `healthy` y no debe existir un bucle de reinicios.

## 6. Nginx

Como `/api/v1` lo resuelve internamente Next.js, Nginx solo necesita un upstream en loopback:

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

Validar **antes** de recargar:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

TLS debe instalarse con el mecanismo autorizado por la universidad: certificado institucional o Certbot si la infraestructura lo permite.

## 7. Verificación funcional

Después de Nginx/TLS:

```bash
curl -fsS https://<SUBDOMINIO_INSTITUCIONAL>/api/v1/health/live && echo
```

Comprobar además:

1. Carga de la página y login.
2. Listado y detalle de convocatorias.
3. Fuentes y última actualización.
4. Worker estable y sin reinicios continuos.
5. Subida/lectura de un documento en MinIO si la función está habilitada.
6. Correo/restablecimiento solo si SMTP/Resend está configurado.

Logs útiles sin mostrar secretos:

```bash
$COMPOSE logs --tail=100 api
$COMPOSE logs --tail=100 worker
$COMPOSE logs --tail=100 web
```

## 8. Backup y restore

Antes de cada actualización ejecuta un backup manual:

```bash
$COMPOSE exec -T backup /scripts/backup-cycle.sh
$COMPOSE exec -T backup /scripts/verify_latest_backup.sh /backups
$COMPOSE logs --tail=50 backup
```

No actualices producción si el ciclo no termina correctamente con `PASS`.

La restauración oficial está en `docs/restore-runbook.md`. PostgreSQL permanece privado; el restore se realiza dentro de la red Docker y primero en `scratch_restore`.

## 9. Actualización segura

Antes de actualizar:

```bash
cd /home/ubuntu/apps/convocaradar
git rev-parse HEAD
COMPOSE='docker compose -p convocaradar --env-file .env -f docker-compose.server.yml'
$COMPOSE exec -T backup /scripts/backup-cycle.sh
$COMPOSE exec -T backup /scripts/verify_latest_backup.sh /backups
```

Luego:

```bash
git fetch --tags origin
git checkout <TAG_O_COMMIT_APROBADO>
EXPECTED_WEB_PORT=3001 bash scripts/server-preflight.sh
$COMPOSE build --pull api worker web backup
$COMPOSE up -d api
$COMPOSE up -d worker backup web
$COMPOSE ps
curl -fsS http://127.0.0.1:3001/api/v1/health/live && echo
```

Si el nuevo contenedor no queda saludable, vuelve al commit anterior y reconstruye la aplicación. Si una migración cambió datos/esquema de forma no compatible, sigue `docs/restore-runbook.md`; no improvises un downgrade.

## 10. Checklist de entrega

- [ ] CI del commit/tag aprobado completamente verde.
- [ ] SHA de producción registrado y worktree limpio.
- [ ] `.env` con permisos `600` y sin placeholders.
- [ ] `scripts/server-preflight.sh` termina en `PREFLIGHT=PASS`.
- [ ] Solo `127.0.0.1:3001` publicado por el stack.
- [ ] PostgreSQL, MinIO y API sin puertos del host.
- [ ] Todos los contenedores `running`; los que tienen healthcheck, `healthy`.
- [ ] Web y `/api/v1/health/live` responden desde loopback.
- [ ] Nginx `nginx -t` correcto y TLS operativo.
- [ ] Login y flujo principal verificados.
- [ ] Worker estable y sin bucle de reinicio.
- [ ] Backup manual y verificación terminan correctamente.
- [ ] Restore a scratch documentado y probado por CI.
- [ ] Commit/tag de producción registrado para rollback.
