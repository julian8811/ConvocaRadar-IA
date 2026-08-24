#!/usr/bin/env bash
set -euo pipefail

backup_dir=/backups
interval_seconds="${BACKUP_INTERVAL_SECONDS:-86400}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
mkdir -p "$backup_dir"

# libpq auth: no other mechanism in the stack provides a password, so pg_dump
# silently failed and the pipeline produced ~20-byte gzip-of-empty archives
# (root cause documented in docs/restore-runbook.md). The compose stack
# injects POSTGRES_PASSWORD; bridge it to libpq here. Never hand pg_dump a
# DATABASE_URL-style URI: `postgresql+psycopg://` is SQLAlchemy driver syntax
# that libpq rejects.
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"
export PGPASSWORD="$POSTGRES_PASSWORD"

while true; do
  timestamp=$(date -u +%Y%m%dT%H%M%SZ)
  target="$backup_dir/convocaradar-$timestamp.sql.gz"
  tmp_target="/tmp/backup-$$.sql.gz"
  
  # Cleanup temp file on exit
  trap 'rm -f "$tmp_target"' EXIT
  
  # Dump to temp file first
  pg_dump -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" | gzip > "$tmp_target"
  
  # Validate size (reject empty dumps < 100 bytes). `wc -c <` is POSIX;
  # `stat -c%s` is GNU-only and fails on macOS/BSD stat.
  size=$(( $(wc -c < "$tmp_target") ))
  if [ "$size" -lt 100 ]; then
    echo "Backup failed: dump too small ($size bytes, expected >100)" >&2
    exit 1
  fi
  
  # Validate gzip integrity
  gzip -t "$tmp_target"
  
  # Atomic move to final location
  mv "$tmp_target" "$target"
  
  # Clear trap after successful move
  trap - EXIT
  
  find "$backup_dir" -type f -name 'convocaradar-*.sql.gz' -mtime "+$retention_days" -delete
  sleep "$interval_seconds"
done
