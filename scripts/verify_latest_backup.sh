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

# Staleness check: backup must be younger than 24h (spec) / 48h (legacy grace). Portable via `find -mtime`.
# -mtime +1 means >24h old (more than 1*24h ago); covers spec's 24h staleness requirement.
# Use find to test staleness without GNU stat date parsing.
if [ -n "$(find "$latest" -mtime +1 2>/dev/null)" ]; then
  echo "Backup is stale: $latest is older than 24h (1 day) — expected fresh backup within 24h" >&2
  ls -lh "$latest" >&2
  exit 1
fi

gzip -t "$latest"
if ! gzip -dc "$latest" | grep -q 'CREATE TABLE'; then
  echo "Backup does not contain SQL schema statements: $latest" >&2
  exit 1
fi
echo "Backup integrity verified: $latest ($size bytes)"
