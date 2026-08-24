#!/bin/sh
set -eu

backup_dir="${1:-backups}"
# POSIX latest-file resolution: `find -printf '%T@'` is a GNU extension that
# crashes on busybox/alpine and macOS/BSD find. Backup filenames contain no
# whitespace, so `ls -t | head -1` is a safe portable equivalent.
latest=$(ls -t "$backup_dir"/convocaradar-*.sql.gz 2>/dev/null | head -n 1)
if [ -z "$latest" ]; then
  echo "No backup found in $backup_dir" >&2
  exit 1
fi

# Check file size (reject empty dumps < 100 bytes). `wc -c <` is POSIX;
# `stat -c%s` is GNU-only and fails on macOS/BSD stat.
size=$(( $(wc -c < "$latest") ))
if [ "$size" -lt 100 ]; then
  echo "Backup too small: $size bytes (expected >100): $latest" >&2
  exit 1
fi

gzip -t "$latest"
if ! gzip -dc "$latest" | grep -q 'CREATE TABLE'; then
  echo "Backup does not contain SQL schema statements: $latest" >&2
  exit 1
fi
echo "Backup integrity verified: $latest ($size bytes)"
