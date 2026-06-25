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
- `SCRAPING_EXECUTION_MODE`
- `USE_WORKER`
- `SCRAPING_TIMEOUT_SECONDS`

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
- `SCRAPING_EXECUTION_MODE=inline`
- `USE_WORKER=false`
- `SCRAPING_TIMEOUT_SECONDS=30`

`SCRAPING_EXECUTION_MODE=inline` ejecuta las capturas manuales dentro del servicio API. Es la opcion mas estable en Render Free. Si el worker esta siempre activo, puedes usar `worker` y mantener `USE_WORKER=true` en el worker.

### Render worker y worker-beat

El blueprint incluye:

- `convocaradar-worker`: ejecuta tareas Celery de scraping.
- `convocaradar-worker-beat`: dispara capturas programadas cada 30 minutos y alertas cada 5 minutos.

Variables minimas compartidas entre worker y beat:

- `DATABASE_URL`
- `REDIS_URL`
- `BACKEND_URL` (URL publica del API, por ejemplo `https://api.convocaradar.com`)
- `INTERNAL_API_KEY` (debe coincidir con el servicio API)

Para diagnosticar conectores en produccion sin persistir datos:

```bash
curl -X POST "$BACKEND_URL/api/v1/internal/connectors/probe" \
  -H "X-Internal-API-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source_key":"minciencias","base_url":"https://minciencias.gov.co/convocatorias/todas"}'
```

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

## Fuentes y vigilancia tecnologica

La oleada 1 del seed incluye 26 fuentes por defecto (19 originales + 7 nuevas). La oleada 2 suma 7 fuentes más (33 total). La oleada 3 suma 5 fuentes (38 total):

| Key | Tipo | Region |
|-----|------|--------|
| `novo-nordisk-grants` | WordPress API | Europa |
| `wellcome-grants` | HTML | UK/Global |
| `horizon-europe-sedia` | SEDIA API | EU |
| `gates-foundation-grants` | HTML | Global |
| `dfg-grants` | HTML | Alemania |
| `colfuturo-convocatorias` | HTML | Colombia |
| `mincit-innovacion` | HTML | Colombia |

Oleada 2:

| Key | Tipo | Región |
|-----|------|--------|
| `lundbeck-foundation` | HTML | Dinamarca |
| `velux-foundation` | HTML | Dinamarca |
| `isciii-convocatorias` | BDN API | España |
| `cdti-convocatorias` | BDN API | España |
| `idrc-funding` | HTML | Canadá/Global |
| `usaid-grants` | Grants.gov API | Global |
| `giz-funding` | HTML | Alemania/Global |

Oleada 3:

| Key | Tipo | Región |
|-----|------|--------|
| `cordis-h2020` | CORDIS API | EU |
| `eic-accelerator` | SEDIA API | EU |
| `global-innovation-fund` | HTML | Global |
| `procolombia-convocatorias` | HTML | Colombia |
| `anii-uruguay` | HTML | Uruguay |

### Reseed en produccion

Las fuentes nuevas en `seed.py` no aparecen automaticamente si la organizacion ya existe. Tras desplegar, ejecuta como admin autenticado:

```bash
curl -X POST "$BACKEND_URL/api/v1/admin/sources/reseed-defaults" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Verifica en Admin que `Fuentes configuradas` sube a 26+.

### Probe de conectores

```bash
curl -X POST "$BACKEND_URL/api/v1/internal/connectors/probe" \
  -H "X-Internal-API-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source_key":"novo-nordisk-grants","base_url":"https://novonordiskfonden.dk/wp-json/wp/v2/grant?per_page=100&status=publish","source_type":"api"}'
```

Criterio de exito para NNF: `candidates_valid >= 50`.

### Matriz de evaluacion mensual

| Criterio | Peso | Descartar si... |
|----------|------|-----------------|
| Acceso tecnico | Alto | Requiere login, CAPTCHA o bloquea IP cloud |
| Estabilidad URL | Alto | Cambia cada mes sin redirects |
| Formato estructurado | Alto | Solo PDF escaneado |
| Cobertura | Medio | Menos de 5 convocatorias activas |
| Relevancia | Medio | Fuera de I+D, cooperacion o innovacion |
| Legal/ToS | Medio | Prohibe scraping explicitamente |
| Latencia | Medio | Mas de 60 s por fuente en Render inline |

### Run-all con 26+ fuentes

`POST /sources/run-all` respeta `scraping_frequency` (fuentes semanales se omiten si corrieron hace menos de 7 dias) y encola fuentes lentas (`innovamos`, `eu-funding-tenders`, `minciencias`, `ukri-opportunities`, `horizon-europe-sedia`, hibridas) al worker cuando `SCRAPING_EXECUTION_MODE=worker` o `auto` con `USE_WORKER=true`. Con `inline`, todas las fuentes elegibles se ejecutan secuencialmente con timeout `SCRAPING_MAX_SOURCE_SECONDS=90`.

## Observaciones importantes

- No existe una plataforma gratis unica que mantenga `Next.js + FastAPI + Celery + Postgres + Redis + storage` encendida 24/7 sin limites.
- Si el scraping debe correr de forma continua, el costo real aparece en el computo del backend o del worker.
- La combinacion gratis mas equilibrada para un MVP es Vercel + Neon + Upstash + R2.
