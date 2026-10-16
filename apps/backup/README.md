# Sidecar de backups (imagen `backup`)

Imagen que ejecuta el ciclo diario de backups de PostgreSQL en el compose
del servidor. La base es `postgres:16-alpine` con `python3` (solo stdlib)
y el planificador `supercronic` pineado por checksum; el proceso principal
es supercronic, que dispara el ciclo cada día a las 03:30 UTC.

## Uso

```bash
docker compose -f docker-compose.server.yml build backup
docker compose -f docker-compose.server.yml up -d backup
```

Variables y secretos (contraseñas, S3/MinIO, retención): ver el servicio
`backup` en `docker-compose.server.yml`. Este README no incluye secretos.

## Piezas

| Pieza | Rol |
|-------|-----|
| `apps/backup/Dockerfile` | Define la imagen: base postgres, python3, supercronic pineado, copia los 4 ficheros de abajo a `/scripts`, CMD supercronic |
| `scripts/backup-cycle.sh` | Ciclo validado one-shot: dump con `pg_dump`, compuertas de tamaño, `mv` atómico y copia off-site best-effort |
| `scripts/backup_offsite.py` | Copia off-site a S3/MinIO con solo stdlib (exit 0 ok, 1 error, 2 omitido sin fallar el ciclo) |
| `scripts/verify_latest_backup.sh` | Verifica el último backup: `[CORRUPT]` (inutilizable) vs `[STALE]` (íntegro pero de hace más de 24 h) |
| `scripts/crontab-backup` | Crontab de supercronic: `30 3 * * * /scripts/backup-cycle.sh` |
| `scripts/backup-loop.sh` | Existe en `scripts/` pero NO se copia a la imagen; el sidecar programa `backup-cycle.sh` vía cron |
| `docker-compose.server.yml` (servicio `backup`) | Dónde se usa la imagen: build, entorno, volumen `backups-data`, espera a `postgres` sano |
| `docs/restore-runbook.md` | Runbook de restauración (causa raíz del puente `PGPASSWORD` documentada ahí) |
