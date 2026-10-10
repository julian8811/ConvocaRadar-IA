# Índice de scripts

Inventario completo de `scripts/` (29 ficheros) y `apps/api/scripts/` (5 ficheros).
Cada entrada indica el propósito en una línea y un comando de ejemplo solo cuando
el encabezado del propio script lo documenta; en caso contrario, remite al encabezado.
No contiene secretos ni valores: únicamente nombres de variables de entorno cuando
el script las requiere.

## Scraper, backfill y enriquecimiento

| Archivo | Propósito | Uso |
|---|---|---|
| `scripts/backfill_enrich_opportunities.py` | Relee páginas de detalle para completar `close_date` y `funding_amount` faltantes. | `python scripts/backfill_enrich_opportunities.py [--dry-run] [--limit 100]` |
| `scripts/backfill_opportunity_status.py` | Recalcula estados (`closed`/`closing_soon`) y limpia URL oficiales rotas. | `python scripts/backfill_opportunity_status.py [--dry-run] [--batch-size 100] [--skip-url-check]` |
| `scripts/backfill_report_quality.py` | Repara calidad de datos para informes (fechas, montos, resúmenes, entidad, estado). | ver encabezado |
| `scripts/scrape_missing_summaries.py` | Genera resúmenes faltantes visitando la página oficial (httpx, Playwright para SPA). | `python scripts/scrape_missing_summaries.py [--limit 20]` |
| `scripts/piloto_full_capture.py` | Arnesa captura completa de campos sobre 20 filas en dry-run (solo fusiones IS-NULL). | `python scripts/piloto_full_capture.py [--limit 20] [--execute]` |
| `scripts/eval_extraction.py` | Evalúa precisión/recall de extractores de montos y fechas con compuerta de cobertura 60 %. | ver encabezado |
| `scripts/maintenance.py` | Limpia corridas fallidas antiguas y corrige países `Por validar`. | `python scripts/maintenance.py --cleanup-runs` · `--fix-countries` · `--all` |
| `scripts/normalize_text_data.py` | Repara mojibake (latin1→utf-8) en columnas de texto de todas las tablas. | ver encabezado |
| `scripts/export_reports_pdf.py` | Exporta informes mensuales a PDF con Chromium/Playwright conservando el diseño. | `python scripts/export_reports_pdf.py --out /ruta/destino [--mes Agosto]` |
| `apps/api/scripts/backfill_022.py` | Backfill directo a BD de montos y fechas con parsers locales (sin LLM). | `python apps/api/scripts/backfill_022.py --dry-run` · `--execute` |
| `apps/api/scripts/probe_funding_candidates.py` | Audita por qué se descartaron candidatos de financiamiento (réplica las guardas de `backfill_022`). | `DATABASE_URL=... python apps/api/scripts/probe_funding_candidates.py [--limit 100]` |
| `apps/api/scripts/re_scrape_detail.py` | Relee páginas de detalle con respaldo Playwright para SPA (p. ej. grants.gov). | `DATABASE_URL=... python apps/api/scripts/re_scrape_detail.py --source grants-gov --limit 2 --dry-run --force-playwright` |
| `apps/api/scripts/bench_golden.py` | Compara similitud coseno real contra el golden `golden_colmayor_20.json`. | `python apps/api/scripts/bench_golden.py` |
| `apps/api/scripts/tune_thresholds.py` | Valida umbrales por facultad candidatos contra el golden (precisión ≥ 80 %). | `python apps/api/scripts/tune_thresholds.py` |

## Fuentes (ciclo de vida de `Source`)

| Archivo | Propósito | Uso |
|---|---|---|
| `scripts/add_developmentaid.py` | Crea la fuente `developmentaid-tenders` si no existe. | ver encabezado |
| `scripts/delete_fonacyt.py` | Elimina la fuente `fonacyt-bolivia` si no tiene oportunidades ni corridas asociadas. | ver encabezado |
| `scripts/update_dane.py` | Corrige URL base y reactiva la fuente `dane-convocatorias`. | ver encabezado |
| `scripts/update_finep.py` | Corrige URL base y reactiva la fuente `finep-brasil`. | ver encabezado |
| `scripts/check_sources_health.py` | Verifica que cada fuente definida responda HTTP 200. | `python scripts/check_sources_health.py [--json] [--quiet]` |
| `scripts/probe_source_contracts.py` | Sondea contratos de fuentes activas sin mutar datos. | ver encabezado |
| `scripts/probe_targeted_sources.py` | Sondea un subconjunto fijo de fuentes por clave. | ver encabezado |
| `scripts/quarantine_blocked_sources.py` | Pausa automática de fuentes con errores conocidos (403/404, host fuera de contrato). | ver encabezado |
| `scripts/reactivate_verified_sources.py` | Reactiva un conjunto verificado de fuentes (limpia errores y pausas). | ver encabezado |
| `scripts/release_recoverable_sources.py` | Libera la pausa de fuentes recuperables puntuales. | ver encabezado |

## Deploy y backup

| Archivo | Propósito | Uso |
|---|---|---|
| `scripts/backup-cycle.sh` | Ciclo único de backup PostgreSQL validado (staging + `mv` atómico, copia off-site). | `PGHOST=... PGPORT=... POSTGRES_USER=... POSTGRES_DB=... POSTGRES_PASSWORD=... BACKUP_DIR=/backups scripts/backup-cycle.sh` |
| `scripts/backup-loop.sh` | Bucle continuo de `pg_dump` con retención de 14 días (ver `BACKUP_INTERVAL_SECONDS`, `BACKUP_RETENTION_DAYS`). | `./scripts/backup-loop.sh` |
| `scripts/backup_offsite.py` | Copia archivos de backup a S3/MinIO (stdlib, códigos 0 ok / 1 error / 2 omitido). | invocado por `backup-cycle.sh`; ver encabezado para `BACKUP_S3_*` |
| `scripts/crontab-backup` | Crontab supercronic: ciclo diario 03:30 UTC del sidecar de backup. | ver encabezado (lo consume supercronic, no se ejecuta a mano) |
| `scripts/verify_latest_backup.sh` | Verifica el backup más nuevo (integridad gzip + esquema; distingue corrupto vs desactualizado). | `sh scripts/verify_latest_backup.sh [backups\|s3://bucket/prefijo]` |
| `scripts/trigger-render-deploy.sh` | Dispara deploy en Render vía hook o API (con reintento y modo no requerido). | `bash scripts/trigger-render-deploy.sh <etiqueta> [hook] [api_key] [service_id] [requerido]` |

## Infra y utilidades

| Archivo | Propósito | Uso |
|---|---|---|
| `scripts/check-secrets.sh` | Detecta secretos comprometidos accidentalmente en el árbol de trabajo. | `bash scripts/check-secrets.sh` |
| `scripts/health-check.py` | Monitoreo de salud vía cron de Render cada 5 minutos (exit 0 ok). | `python scripts/health-check.py` (ver `HEALTH_CHECK_URL`, `HEALTH_CHECK_TIMEOUT`) |
| `scripts/server-preflight.sh` | Verificación previa al servidor: docker, compose, permisos de `.env`, URLs y puertos. | `./scripts/server-preflight.sh` |
| `scripts/sync-next-output.mjs` | Copia `apps/web/.next` a `.next` en la raíz para despliegues que lo esperan allí. | `node scripts/sync-next-output.mjs` |

## Cobertura

34 ficheros documentados: 29 en `scripts/` + 5 en `apps/api/scripts/`.
Verificado con `ls scripts/` y `ls apps/api/scripts/` el 2026-10-10.
Si se agrega un script nuevo, añadir su fila en el grupo correspondiente.
