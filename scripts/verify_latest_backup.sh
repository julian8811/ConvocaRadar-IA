#!/bin/sh
set -eu

backup_dir="${1:-backups}"
latest=$(find "$backup_dir" -maxdepth 1 -type f -name 'convocaradar-*.sql.gz' -printf '%T@ %p\n' | sort -nr | sed -n '1s/^[^ ]* //p')
if [ -z "$latest" ]; then
  echo "No backup found in $backup_dir" >&2
  exit 1
fi

gzip -t "$latest"
if ! gzip -dc "$latest" | grep -q 'CREATE TABLE'; then
  echo "Backup does not contain SQL schema statements: $latest" >&2
  exit 1
fi
echo "Backup integrity verified: $latest"
