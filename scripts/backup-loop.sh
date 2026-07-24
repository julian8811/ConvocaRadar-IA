#!/bin/sh
set -eu

backup_dir=/backups
interval_seconds="${BACKUP_INTERVAL_SECONDS:-86400}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
mkdir -p "$backup_dir"

while true; do
  timestamp=$(date -u +%Y%m%dT%H%M%SZ)
  target="$backup_dir/convocaradar-$timestamp.sql.gz"
  pg_dump -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" | gzip > "$target"
  gzip -t "$target"
  find "$backup_dir" -type f -name 'convocaradar-*.sql.gz' -mtime "+$retention_days" -delete
  sleep "$interval_seconds"
done
