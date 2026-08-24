# Restore Runbook — ConvocaRadar PostgreSQL backups

Audience: operator on call for the ConvocaRadar compose stack. This document
explains why the backup pipeline was rebuilt (July 2026 empty-backup incident),
how the nightly cycle works, how to run a manual cycle, and how to restore.

## 1. Incident root cause (why dumps were ~20 bytes)

Between **2026-07-22 and this fix**, every scheduled backup produced a valid but
**empty** `.sql.gz` (~20 bytes). The last real backup is dated **2026-07-21**.

Root cause chain, reproduced mechanically against the committed script:

1. `scripts/backup-loop.sh` invoked `pg_dump -h postgres -U "$POSTGRES_USER"`
   with **no password mechanism anywhere in the stack** — no `PGPASSWORD`, no
   `.pgpass`. Against a password-protected server, pg_dump fails authentication
   and writes nothing to stdout.
2. The script ran under `/bin/sh` with `set -eu` only. POSIX shells have no
   `pipefail`, so the pipeline `pg_dump | gzip > file` reported the exit status
   of its **last** command: `gzip` succeeded compressing the empty stream.
3. `gzip -t` passed, because the archive *is* valid gzip — of zero bytes.

Reproduction (stubbed `pg_dump` that prints the auth error to stderr, exits 1):

```console
$ PATH="…:$PATH" sh -ec 'pg_dump -h postgres -U convocaradar -d convocaradar | gzip > old-pattern.sql.gz'
pg_dump: error: fe_sendauth: no password supplied
$ echo $?            # pipeline status under set -e, no pipefail
0
$ wc -c < old-pattern.sql.gz
20
$ gzip -t old-pattern.sql.gz && echo PASSES   # old gate accepts it
PASSES
```

Secondary trap, documented so it stays dead: never pass a `DATABASE_URL`-style
URI to `pg_dump`. The app's `postgresql+psycopg://` scheme is SQLAlchemy
driver syntax; libpq rejects it outright. Credentials travel as discrete vars
(`PGHOST`, `PGPORT`, `POSTGRES_USER`, `POSTGRES_DB`, bridged `PGPASSWORD`).

## 2. Backup architecture after the fix

| Piece | Location | Role |
|---|---|---|
| Cycle script | `scripts/backup-cycle.sh` | One dump → validate → publish → verify → prune cycle |
| Schedule | `scripts/crontab-backup` | supercronic entry: daily at **03:30 UTC** |
| Sidecar service | `docker-compose.yml` → `backup:` | `postgres:16-alpine`, restart unless-stopped, runs supercronic as PID 1 |
| Verification | `scripts/verify_latest_backup.sh` | Newest-archive integrity + schema-marker check |
| Retention | `BACKUP_RETENTION_DAYS` (default **14**) | Older `convocaradar-*.sql.gz` pruned each cycle |

The sidecar image must be `postgres:16-alpine`: the `pg_dump` client major
version has to match the server major version. The stack's database is pg16.

Cycle stages, all inside `backup-cycle.sh`:

1. Dump plain SQL directly to a staging file (no pipeline — keeps pg_dump's
   exit status observable where POSIX sh lacks `pipefail`).
2. Compress the staged dump with `gzip`.
3. Size gate: reject archives < 100 bytes (the gzip-of-empty signature).
4. Integrity gate: `gzip -t`.
5. Atomic `mv` into `BACKUP_DIR`; readers never see partial archives.
6. Prune archives older than the retention window.
7. Run `verify_latest_backup.sh` **in-cycle** against the newest archive.

Failure contract: any failed stage exits non-zero with an actionable log line;
success ends with a `[backup-cycle] … PASS:` marker. Nothing is published
unless all gates passed. The retained long-run alternative
`scripts/backup-loop.sh` received the same auth and portability repairs.

Portability note: size uses `wc -c` and latest-file selection uses
`ls -t | head -1`. The previous GNU-only forms (`stat -c%s`,
`find -printf '%T@'`) crash on busybox/alpine and macOS/BSD — verified by
running the scripts with a restricted `PATH` lacking those tools (valid backup
went from exit 127 to verified OK).

## 3. Running a manual cycle

Against the compose stack (from the host):

```console
$ docker compose exec backup /scripts/backup-cycle.sh
```

Against any reachable PostgreSQL from a machine with the client installed:

```console
$ PGHOST=127.0.0.1 PGPORT=5432 POSTGRES_USER=convocaradar \
  POSTGRES_DB=convocaradar POSTGRES_PASSWORD=… BACKUP_DIR=/backups \
  scripts/backup-cycle.sh
[backup-cycle] 2026-08-24T01:47:57Z starting pg_dump of convocaradar@127.0.0.1:5544
[backup-cycle] 2026-08-24T01:47:57Z published …/convocaradar-20260824T014757Z.sql.gz (1191 bytes)
Backup integrity verified: …/convocaradar-20260824T014757Z.sql.gz (1191 bytes)
[backup-cycle] 2026-08-24T01:47:57Z PASS: backup + verify completed for cycle 20260824T014757Z
```

Scheduled output lands in container logs: `docker compose logs backup`.

## 4. Restore procedure

1. List candidates and pick the archive to restore (newest first):

   ```console
   $ ls -lt /var/lib/docker/volumes/convocaradar_backups-data/_data/
   ```

2. Create an empty scratch database — restore into scratch first, never
   straight over the live database:

   ```console
   $ createdb -h 127.0.0.1 -p 5434 -U convocaradar scratch_restore
   ```

3. Restore (plain-SQL archives are streamed straight into psql):

   ```console
   $ gunzip -c convocaradar-TIMESTAMP.sql.gz \
       | psql -h 127.0.0.1 -p 5434 -U convocaradar -d scratch_restore
   ```

4. Sanity checks before promoting the restore:

   ```sql
   SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';
   SELECT count(*) FROM opportunities;
   ```

5. To promote: point the app at the restored database or swap roles/databases,
   then re-run one backup cycle against the promoted instance.

## 5. Executed-once evidence (2026-08-24)

Executed end-to-end on a disposable local PostgreSQL 16 cluster (trust auth,
port 5544), exercising the exact committed scripts:

* Source state created via psql: table `opportunities`, **rows = 50**.
* `backup-cycle.sh` against the cluster: published
  `convocaradar-20260824T014757Z.sql.gz` (**1191 bytes**), in-cycle verify
  passed, exit code **0**, `PASS` marker logged.
* Restored the archive into `scratch_restore` via step 3 above.
* Post-restore sanity: **tables = 1**, **rows = 50**, `max(score) = 75.0`
  (matches source data exactly).

Stubbed failure-path proofs recorded for the same committed script (fake
`pg_dump` on `PATH`): auth-fail dump, mid-dump failure, tiny archive, failing
in-cycle verification, and missing `POSTGRES_PASSWORD` each exited non-zero,
published nothing, and left no temp files behind.

## 6. Known deferrals

* Container-level compose proof (`docker compose up backup`, supercronic boot,
  scheduled-fire observation) requires a Docker daemon; none exists in this
  environment. Delegated to CI (which starts services explicitly and can add
  `docker compose up -d backup`) or to ops during first production rollout.
* Restore timings/volumes above reflect a 1-table fixture; production-scale
  restore duration should be measured during the next drill.
