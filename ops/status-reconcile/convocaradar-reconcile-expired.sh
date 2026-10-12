#!/usr/bin/env bash
# Daily closure reconciliation, preview-only unless explicitly called "apply".
set -Eeuo pipefail
MODE="${1:-preview}"
if [[ "$MODE" != "preview" && "$MODE" != "apply" ]]; then
  echo "Uso: $0 [preview|apply]" >&2
  exit 2
fi
PG_CONTAINER="convocaradar-postgres-1"
if ! /usr/bin/docker inspect --format '{{.State.Running}}' "$PG_CONTAINER" 2>/dev/null | grep -qx true; then
  echo "ERROR: el contenedor de PostgreSQL no está ejecutándose" >&2
  exit 1
fi
exec 9>/run/lock/convocaradar-status-reconcile.lock
if ! /usr/bin/flock -n 9; then
  echo "Ya existe una conciliación en curso; se omite esta ejecución"
  exit 0
fi
printf 'ConvocaRadar | %s | %s\n' "$MODE" "$(date -u +%FT%TZ)"
if [[ "$MODE" == "preview" ]]; then
  /usr/bin/docker exec -i "$PG_CONTAINER" \
    psql -U convocaradar -d convocaradar -v ON_ERROR_STOP=1 -P pager=off <<'SQL'
BEGIN TRANSACTION READ ONLY;
SET LOCAL TIME ZONE 'UTC';
SELECT
  COUNT(*) AS candidatos,
  COUNT(*) FILTER (WHERE status = 'open') AS estado_open,
  COUNT(*) FILTER (WHERE status = 'closing_soon') AS estado_closing_soon
FROM opportunities
WHERE status IN ('open', 'closing_soon')
  AND close_date IS NOT NULL
  AND close_date::date < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date;
ROLLBACK;
SQL
else
  /usr/bin/docker exec -i "$PG_CONTAINER" \
    psql -U convocaradar -d convocaradar -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
DO $$
DECLARE
  v_expected integer;
  v_updated integer;
BEGIN
  SELECT COUNT(*) INTO v_expected
  FROM opportunities
  WHERE status IN ('open', 'closing_soon')
    AND close_date IS NOT NULL
    AND close_date::date < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date;

  IF v_expected > 500 THEN
    RAISE EXCEPTION
      'Se canceló la conciliación: % registros exceden el tope de 500',
      v_expected;
  END IF;

  UPDATE opportunities
  SET status = 'closed'
  WHERE status IN ('open', 'closing_soon')
    AND close_date IS NOT NULL
    AND close_date::date < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date;
  GET DIAGNOSTICS v_updated = ROW_COUNT;

  IF v_updated <> v_expected THEN
    RAISE EXCEPTION
      'Cambio concurrente: se esperaban %, se actualizaron %',
      v_expected, v_updated;
  END IF;
  RAISE NOTICE
    'Conciliación finalizada: candidatos=%, actualizados=%',
    v_expected, v_updated;
END $$;
COMMIT;
SQL
fi
