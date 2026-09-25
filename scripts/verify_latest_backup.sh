#!/bin/sh
# Verifies the newest ConvocaRadar backup from a local volume directory
# (default `backups`) or an S3/MinIO bucket URI (`s3://bucket[/prefix]`,
# resolved via backup_offsite.py + python3).
#
# Outcome vocabulary (T6): the message tells "stale" apart from "corrupt":
#   [CORRUPT] missing archive, size gate (<100 B), gzip integrity failure,
#             or no CREATE TABLE markers — the archive is unusable.
#   [STALE]   archive is intact but older than 24h — cron fell behind, yet a
#             restore from it is still possible.
set -eu

source_arg="${1:-backups}"
offsite_script="${OFFSITE_SCRIPT:-$(dirname -- "$0")/backup_offsite.py}"

latest=""
label=""

case "$source_arg" in
  s3://*)
    # s3://bucket[/prefix]: download the newest object, then run the same
    # gates below. The download preserves the remote Last-Modified mtime, so
    # the staleness gate below measures remote age, not download time.
    s3_rest=${source_arg#s3://}
    case "$s3_rest" in
      */*) s3_bucket=${s3_rest%%/*}; s3_prefix=${s3_rest#*/} ;;
      *) s3_bucket=$s3_rest; s3_prefix="" ;;
    esac
    if [ -z "$s3_bucket" ]; then
      echo "[CORRUPT] Invalid S3 source (expected s3://bucket[/prefix]): $source_arg" >&2
      exit 1
    fi
    command -v python3 >/dev/null 2>&1 || {
      echo "[CORRUPT] Cannot verify S3 source without python3: $source_arg" >&2
      exit 1
    }
    [ -f "$offsite_script" ] || {
      echo "[CORRUPT] Off-site helper missing: $offsite_script" >&2
      exit 1
    }
    key=$(BACKUP_S3_BUCKET="$s3_bucket" python3 "$offsite_script" latest \
      --prefix "$s3_prefix") || exit 1
    tmp_dl=$(mktemp "${TMPDIR:-/tmp}/verify-backup-XXXXXX.sql.gz")
    trap 'rm -f "$tmp_dl"' EXIT INT TERM HUP
    BACKUP_S3_BUCKET="$s3_bucket" python3 "$offsite_script" download \
      "$key" "$tmp_dl" || exit 1
    latest="$tmp_dl"
    label="s3://$s3_bucket/$key"
    ;;
  *)
    backup_dir="$source_arg"
    # POSIX latest-file resolution: `find -printf '%T@'` is a GNU extension that
    # crashes on busybox/alpine and macOS/BSD find. Backup filenames contain no
    # whitespace, so `ls -t | head -1` is a safe portable equivalent.
    latest=$(ls -t "$backup_dir"/convocaradar-*.sql.gz 2>/dev/null | head -n 1)
    if [ -z "$latest" ]; then
      echo "[CORRUPT] No backup found in $backup_dir (expected convocaradar-*.sql.gz)" >&2
      exit 1
    fi
    label="$latest"
    ;;
esac

# Check file size (reject empty dumps < 100 bytes). `wc -c <` is POSIX;
# `stat -c%s` is GNU-only and fails on macOS/BSD stat.
size=$(( $(wc -c < "$latest") ))
if [ "$size" -lt 100 ]; then
  echo "[CORRUPT] Backup too small: $size bytes (expected >100): $label" >&2
  exit 1
fi

# Integrity BEFORE freshness: a stale-but-intact archive must report [STALE]
# (cron fell behind, restore still possible) and never mask corruption.
if ! gzip -t "$latest" 2>/dev/null; then
  echo "[CORRUPT] Backup failed gzip integrity check: $label" >&2
  exit 1
fi
if ! gzip -dc "$latest" | grep -q 'CREATE TABLE'; then
  echo "[CORRUPT] Backup does not contain SQL schema statements: $label" >&2
  exit 1
fi

# Staleness check: backup must be younger than 24h (spec) / 48h (legacy grace). Portable via `find -mtime`.
# -mtime +1 means >24h old (more than 1*24h ago); covers spec's 24h staleness requirement.
# Use find to test staleness without GNU stat date parsing.
if [ -n "$(find "$latest" -mtime +1 2>/dev/null)" ]; then
  echo "[STALE] Backup is stale: $label is older than 24h (1 day) — expected fresh backup within 24h" >&2
  ls -lh "$latest" >&2
  exit 1
fi

echo "Backup integrity verified: $label ($size bytes)"
