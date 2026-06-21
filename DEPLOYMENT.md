# Despliegue de ConvocaRadar IA

Este proyecto no tiene un solo destino gratuito perfecto para todo el stack. La ruta mas realista para una version publica gratis es separar responsabilidades:

- Frontend: Vercel Hobby
- Base de datos: Neon Free con `pgvector`
- Redis: Upstash Free
- Archivos: Cloudflare R2 Free
- API y worker: Render como capa de computo

## Que falta antes de publicar

1. Crear los servicios externos.
2. Enlazar el frontend con la URL publica del backend.
3. Configurar `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `INTERNAL_API_KEY` y credenciales de storage.
4. Habilitar la extension `vector` en Postgres.
5. Verificar que el worker pueda alcanzar el backend publico.
6. Ejecutar migraciones una sola vez antes de abrir trafico.

## Variables por servicio

Nota: `POSTGRES_DATABASE_URL` se usa solo en el flujo local de Docker Compose. En produccion, la variable que debe quedar configurada es `DATABASE_URL`.

### Vercel

Variables publicas:

- `NEXT_PUBLIC_API_URL`
- `FRONTEND_URL`

Valores sugeridos:

- `NEXT_PUBLIC_API_URL=https://api.convocaradar.com/api/v1`
- `FRONTEND_URL=https://convocaradar.com`

### Render API

Variables privadas:

- `DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET`
- `INTERNAL_API_KEY`
- `BACKEND_URL`
- `FRONTEND_URL`
- `STORAGE_BACKEND`
- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_BUCKET`
- `S3_REGION`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_USE_TLS`
- `LLM_PROVIDER`
- `OPENAI_API_KEY`
- `EMBEDDING_MODEL`
- `CHAT_MODEL`

Valores sugeridos:

- `DATABASE_URL=postgresql+psycopg://...`
- `REDIS_URL=rediss://...`
- `JWT_SECRET=<secreto-largo>`
- `INTERNAL_API_KEY=<secreto-largo>`
- `BACKEND_URL=https://api.convocaradar.com`
- `FRONTEND_URL=https://convocaradar.com`
- `STORAGE_BACKEND=s3`
- `S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com`
- `S3_ACCESS_KEY=<access-key>`
- `S3_SECRET_KEY=<secret-key>`
- `S3_BUCKET=convocaradar`
- `S3_REGION=auto`
- `SMTP_HOST=<smtp-host>`
- `SMTP_PORT=587`
- `SMTP_USER=<smtp-user>`
- `SMTP_PASSWORD=<smtp-password>`
- `SMTP_FROM=alerts@convocaradar.com`
- `SMTP_USE_TLS=true`
- `LLM_PROVIDER=mock` o `openai`
- `OPENAI_API_KEY=<api-key>`
- `EMBEDDING_MODEL=text-embedding-3-small`
- `CHAT_MODEL=gpt-4.1-mini`

### Render worker

Variables privadas:

- `DATABASE_URL`
- `REDIS_URL`
- `BACKEND_URL`
- `INTERNAL_API_KEY`
- `STORAGE_BACKEND`
- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_BUCKET`
- `S3_REGION`

Valores sugeridos:

- `DATABASE_URL=postgresql+psycopg://...`
- `REDIS_URL=rediss://...`
- `BACKEND_URL=https://api.convocaradar.com`
- `INTERNAL_API_KEY=<mismo-valor-que-api>`
- `STORAGE_BACKEND=s3`
- `S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com`
- `S3_ACCESS_KEY=<access-key>`
- `S3_SECRET_KEY=<secret-key>`
- `S3_BUCKET=convocaradar`
- `S3_REGION=auto`

### Neon

No requiere variables de la aplicacion dentro de Vercel ni Render. Solo necesitas:

- `DATABASE_URL`

La conexion debe apuntar a un Postgres con la extension `vector` habilitada:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Upstash

No requiere variables adicionales, solo copiar la URL de conexion y usarla como:

- `REDIS_URL`

### Cloudflare R2

Variables necesarias:

- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_BUCKET`
- `S3_REGION`

La region para compatibilidad S3 debe ser `auto`.

## Matriz de despliegue rapida

| Plataforma | Rol | Variables clave |
|---|---|---|
| Vercel | Frontend | `NEXT_PUBLIC_API_URL`, `FRONTEND_URL` |
| Render API | FastAPI | `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `INTERNAL_API_KEY`, `BACKEND_URL`, `FRONTEND_URL`, storage, SMTP, LLM |
| Render worker | Celery worker | `DATABASE_URL`, `REDIS_URL`, `BACKEND_URL`, `INTERNAL_API_KEY`, storage |
| Neon | Postgres | `DATABASE_URL` |
| Upstash | Redis | `REDIS_URL` |
| Cloudflare R2 | Archivos | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION=auto` |

## Orden recomendado

### 1) Base de datos

Crear un proyecto en Neon, conectar la base de datos e instalar `pgvector`:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2) Redis

Crear una base de Upstash y copiar su URL en `REDIS_URL`.

### 3) Storage

Crear un bucket en Cloudflare R2 y configurar:

- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_BUCKET`
- `S3_REGION=auto`

### 4) Backend

Publicar `apps/api` en Render y apuntarlo a la base de datos y Redis administrados.

### 5) Worker

Publicar `apps/worker` en Render con el mismo Redis y backend publico.

### 6) Frontend

Publicar `apps/web` en Vercel y apuntarlo a la URL publica del API.

### 7) Validacion final

Antes de abrir el sistema al publico:

1. Verificar login.
2. Verificar que el dashboard lea oportunidades reales.
3. Ejecutar un scraper manual y confirmar que actualiza fuentes, graficas y oportunidades.
4. Confirmar que los reportes descargan y que los enlaces funcionan.
5. Confirmar que los correos salen desde SMTP real o, si no hay SMTP, dejar alerts en modo desactivado.

## Observaciones importantes

- No existe una plataforma gratis unica que mantenga `Next.js + FastAPI + Celery + Postgres + Redis + storage` encendida 24/7 sin limites.
- Si el scraping debe correr de forma continua, el costo real aparece en el computo del backend o del worker.
- La combinacion gratis mas equilibrada para un MVP es Vercel + Neon + Upstash + R2.
