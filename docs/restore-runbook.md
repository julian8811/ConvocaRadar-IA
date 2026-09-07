# Restore Runbook — ConvocaRadar PostgreSQL backups

Audience: operador de ConvocaRadar en la VM universitaria.

Este runbook describe backup, verificación y restauración para el stack de producción definido por `docker-compose.server.yml`. PostgreSQL **no publica un puerto en el host**; todas las operaciones se ejecutan dentro de la red Docker mediante `docker compose exec`.

## 1. Contexto y contrato de seguridad

En julio de 2026 se detectaron backups gzip válidos pero vacíos (~20 bytes). La causa fue una combinación de autenticación ausente para `pg_dump` y un pipeline sin `pipefail`, que permitía que `gzip` ocultara el fallo de `pg_dump`.

La implementación actual evita esa clase de error:

1. `pg_dump` escribe primero un SQL temporal y su código de salida se comprueba directamente.
2. El SQL se comprime solo después de un dump exitoso.
3. Se rechazan archivos demasiado pequeños.
4. Se ejecuta `gzip -t`.
5. El archivo se publica mediante `mv` atómico.
6. `verify_latest_backup.sh` comprueba integridad y marcadores de esquema.
7. El ciclo exitoso termina con un marcador `PASS`.

Nunca se debe considerar válido un backup solo porque `gzip -t` pasa.

## 2. Variables operativas

Desde el checkout de producción:

```bash
cd /home/ubuntu/apps/convocaradar
COMPOSE='docker compose -p convocaradar --env-file .env -f docker-compose.server.yml'
```

No imprimas `.env` ni exportes secretos al historial de shell. El contenedor `backup` recibe las credenciales PostgreSQL desde Compose.

Los backups viven en el volumen Docker `convocaradar_backups-data` y la retención se controla con `BACKUP_RETENTION_DAYS` (14 días por defecto).

## 3. Backup manual obligatorio antes de actualizar

Ejecuta:

```bash
$COMPOSE exec -T backup /scripts/backup-cycle.sh
$COMPOSE exec -T backup /scripts/verify_latest_backup.sh /backups
$COMPOSE logs --tail=50 backup
```

El primer comando debe terminar en código 0 y registrar un mensaje similar a:

```text
[backup-cycle] ... PASS: backup + verify completed ...
```

No continúes con una actualización si el ciclo o la verificación fallan.

Para confirmar que existe un archivo publicado sin extraerlo del volumen:

```bash
$COMPOSE exec -T backup sh -c 'ls -lh -t /backups/convocaradar-*.sql.gz | head'
```

## 4. Restauración segura en una base scratch

La regla es: **restaurar y validar primero en `scratch_restore`; nunca restaurar directamente sobre la base viva como primer paso**.

### 4.1 Seleccionar el backup más reciente

```bash
latest="$($COMPOSE exec -T backup sh -c 'ls -t /backups/convocaradar-*.sql.gz | head -n 1' | tr -d '\r')"
test -n "$latest" || { echo 'ERROR: no backup found'; exit 1; }
printf 'Backup seleccionado: %s\n' "$latest"
```

### 4.2 Recrear la base scratch

Esto solo modifica `scratch_restore`; no toca `convocaradar`:

```bash
$COMPOSE exec -T postgres dropdb --if-exists -U convocaradar scratch_restore
$COMPOSE exec -T postgres createdb -U convocaradar scratch_restore
```

### 4.3 Restaurar dentro de la red Docker

```bash
$COMPOSE exec -T backup sh -c "gzip -dc '$latest'" \
  | $COMPOSE exec -T postgres \
      psql -v ON_ERROR_STOP=1 -U convocaradar -d scratch_restore
```

No uses `127.0.0.1:5434` ni publiques temporalmente PostgreSQL para restaurar. El Compose de producción mantiene PostgreSQL privado.

## 5. Verificación del restore

Compara la revisión Alembic:

```bash
source_revision="$($COMPOSE exec -T postgres psql -U convocaradar -d convocaradar -tAc 'SELECT version_num FROM alembic_version' | tr -d '\r')"
restored_revision="$($COMPOSE exec -T postgres psql -U convocaradar -d scratch_restore -tAc 'SELECT version_num FROM alembic_version' | tr -d '\r')"
printf 'source=%s restored=%s\n' "$source_revision" "$restored_revision"
test "$source_revision" = "$restored_revision"
```

Compara el número de tablas y confirma una tabla esencial:

```bash
source_tables="$($COMPOSE exec -T postgres psql -U convocaradar -d convocaradar -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" | tr -d '\r')"
restored_tables="$($COMPOSE exec -T postgres psql -U convocaradar -d scratch_restore -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" | tr -d '\r')"
printf 'source_tables=%s restored_tables=%s\n' "$source_tables" "$restored_tables"
test "$source_tables" = "$restored_tables"
test "$($COMPOSE exec -T postgres psql -U convocaradar -d scratch_restore -tAc "SELECT to_regclass('public.opportunities') IS NOT NULL" | tr -d '\r')" = 't'
```

Cuando existan datos reales, añade verificaciones funcionales apropiadas (por ejemplo recuentos de oportunidades, usuarios u otras entidades críticas) antes de considerar utilizable el restore.

## 6. Promoción de un restore a producción

Promover un restore es una operación de recuperación, no una actualización rutinaria. Hazlo solo si la base viva debe recuperarse desde backup.

1. Registra el commit activo:

   ```bash
   git rev-parse HEAD
   ```

2. Si la base viva aún es legible, intenta un backup manual adicional y conserva su resultado.
3. Valida `scratch_restore` con la sección anterior.
4. Detén los servicios que pueden escribir, dejando PostgreSQL disponible:

   ```bash
   $COMPOSE stop web worker api backup
   ```

5. Antes de sustituir la base viva, confirma que no quedan conexiones de aplicación:

   ```bash
   $COMPOSE exec -T postgres psql -U convocaradar -d postgres -tAc \
     "SELECT count(*) FROM pg_stat_activity WHERE datname='convocaradar' AND pid <> pg_backend_pid();"
   ```

6. La sustitución de `convocaradar` es destructiva. Solo después de tener un `scratch_restore` validado y un backup conservado, recrea la base viva y carga el mismo archivo aprobado:

   ```bash
   $COMPOSE exec -T postgres dropdb -U convocaradar convocaradar
   $COMPOSE exec -T postgres createdb -U convocaradar convocaradar
   $COMPOSE exec -T backup sh -c "gzip -dc '$latest'" \
     | $COMPOSE exec -T postgres \
         psql -v ON_ERROR_STOP=1 -U convocaradar -d convocaradar
   ```

7. Verifica Alembic y tablas nuevamente en la base viva y luego levanta la aplicación:

   ```bash
   $COMPOSE up -d api
   $COMPOSE up -d worker backup web
   $COMPOSE ps
   curl -fsS http://127.0.0.1:3001/api/v1/health/live && echo
   ```

8. Ejecuta un nuevo ciclo de backup después de la recuperación.

Si cualquier comprobación previa falla, **no borres la base viva**.

## 7. Evidencia automatizada vigente

El job `server-smoke` del CI reproduce el flujo de producción con `docker-compose.server.yml` y valida automáticamente:

- PostgreSQL y MinIO saludables;
- persistencia del volumen PostgreSQL después de recrear el contenedor;
- arranque de API, worker, backup y web;
- migración limpia hasta `alembic head`;
- backup real y `verify_latest_backup.sh`;
- restauración del backup más reciente en `scratch_restore`;
- igualdad de revisión Alembic y cantidad de tablas entre origen y restauración;
- existencia de la tabla `opportunities` en la restauración;
- limpieza del stack efímero al terminar.

El procedimiento de las secciones 4 y 5 se mantiene deliberadamente alineado con ese gate de CI.

## 8. Programación y retención

El contenedor `backup` ejecuta Supercronic con `scripts/crontab-backup`. La programación normal es diaria a las 03:30 UTC y la retención predeterminada es 14 días.

Revisar estado y logs:

```bash
$COMPOSE ps backup
$COMPOSE logs --tail=100 backup
```

## 9. Checklist de recuperación

- [ ] Commit activo registrado.
- [ ] Backup seleccionado existe y pasa `verify_latest_backup.sh`.
- [ ] Restore a `scratch_restore` termina sin errores.
- [ ] Revisión Alembic coincide.
- [ ] Conteo de tablas coincide.
- [ ] `opportunities` existe en scratch.
- [ ] Se realizaron comprobaciones de datos críticos.
- [ ] Servicios escritores detenidos antes de cualquier sustitución de la base viva.
- [ ] La base viva no se elimina si falla alguna comprobación previa.
- [ ] Después de recuperar, API/web están saludables y se genera un nuevo backup.
