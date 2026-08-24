#!/bin/sh
# One-shot validated PostgreSQL backup cycle for the ConvocaRadar compose
# stack. Invoked by supercronic inside the `backup:` sidecar (see
# crontab-backup); safe to run manually against any reachable database:
#
#   PGHOST=127.0.0.1 PGPORT=5432 POSTGRES_USER=convocaradar \
#   POSTGRES_DB=convocaradar POSTGRES_PASSWORD=secret BACKUP_DIR=/backups \
#   scripts/backup-cycle.sh
#
# Failure contract: every failure exits non-zero after logging an actionable
# message; success logs a PASS marker. Nothing is published under BACKUP_DIR
# unless the dump passed all gates (staging + atomic mv).
set -eu

backup_dir="${BACKUP_DIR:-/backups}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
dump_host="${PGHOST:-postgres}"
dump_port="${PGPORT:-5432}"
verify_script="${VERIFY_SCRIPT:-$(dirname -- "$0")/verify_latest_backup.sh}"

: "${POSTGRES_USER:?POSTGRES_USER must be set}"
: "${POSTGRES_DB:?POSTGRES_DB must be set}"
# libpq reads PGPASSWORD; the compose stack injects POSTGRES_PASSWORD, so
# bridge it here. Never pass a DATABASE_URL-style URI to pg_dump: the
# `postgresql+psycopg://` scheme is SQLAlchemy driver syntax that libpq
# rejects (root-cause notes in docs/restore-runbook.md).
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"
export PGPASSWORD="$POSTGRES_PASSWORD"

log() { printf '[backup-cycle] %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$backup_dir/convocaradar-$timestamp.sql.gz"
tmp_gz="$backup_dir/.tmp-$timestamp.sql.gz"
tmp_sql="$backup_dir/.tmp-$timestamp.sql"

mkdir -p "$backup_dir"
trap 'rm -f "$tmp_sql" "$tmp_gz"' EXIT INT TERM HUP

# Stage 1: dump plain SQL straight to a file. No pipeline: POSIX sh lacks
# pipefail, so `pg_dump | gzip` masks a failed dump and archives an empty
# stream — the July 2026 empty-backup incident. Direct redirection keeps
# pg_dump's exit status observable under set -e.
log "starting pg_dump of $POSTGRES_DB@$dump_host:$dump_port"
pg_dump -h "$dump_host" -p "$dump_port" -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$tmp_sql"

# Stage 2: compress the completed dump.
gzip -c "$tmp_sql" > "$tmp_gz"
rm -f "$tmp_sql"

# Gate 1: reject suspiciously small archives (<100 B is the gzip-of-empty
# signature that shipped silently for weeks).
size=$(( $(wc -c < "$tmp_gz") ))
if [ "$size" -lt 100 ]; then
  log "FAIL: dump too small ($size bytes, expected >100); refusing to publish"
  exit 1
fi

# Gate 2: archive integrity.
gzip -t "$tmp_gz"

# Atomic publish: readers of BACKUP_DIR only ever see complete archives.
mv "$tmp_gz" "$target"
trap - EXIT INT TERM HUP
log "published $target ($size bytes)"

# Retention: prune archives older than BACKUP_RETENTION_DAYS (default 14).
find "$backup_dir" -maxdepth 1 -type f -name 'convocaradar-*.sql.gz' \
  -mtime "+$retention_days" -delete

# In-cycle verification of whatever is now the newest archive: a scheduled
# cycle that produces a bad backup must fail loudly, not wait for restore day.
"$verify_script" "$backup_dir"

log "PASS: backup + verify completed for cycle $timestamp"
