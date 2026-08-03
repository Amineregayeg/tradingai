# Restoring from backup

Read this before you need it. The commands below are the ones to run during an
incident, when nobody wants to be reasoning from first principles.

Backups live on the VPS at `~/tradingai-backups/` (user `deploy`), one directory
per run, named `YYYYMMDD-HHMMSS`:

```
20260803-121930/
  database.dump          pg_dump custom format — the whole database
  dominance/*.csv        the intraday dominance series (UNRECOVERABLE data)
```

`status.json` records whether the last run succeeded. A directory ending
`.UNVERIFIED` is a **failed** backup kept deliberately as evidence — never
restore from one without understanding why it failed.

## Is there a good backup right now?

```bash
ssh pfe-vps '~/tradingai-backups/backup.sh --status'
```

Exit 0 means the last run verified. Exit 1 means it failed **or is more than
48h stale** — staleness is treated as failure, because a status file saying "ok"
from three weeks ago is worse than no status file at all.

## Restore everything (total loss of the database)

```bash
ssh pfe-vps
cd ~/tradingai-backups/<TIMESTAMP>

# 1. stop the app so nothing writes while the data is inconsistent.
#    Leave the DB container running — it is what performs the restore.
cd /docker/tradingai && docker compose stop api web

# 2. recreate an empty database
docker exec tradingai-db-1 psql -U tradingai -d postgres \
  -c "DROP DATABASE IF EXISTS tradingai;" -c "CREATE DATABASE tradingai;"

# 3. restore
docker exec -i tradingai-db-1 pg_restore -U tradingai -d tradingai --no-owner \
  < ~/tradingai-backups/<TIMESTAMP>/database.dump

# 4. check what came back BEFORE starting the app
docker exec tradingai-db-1 psql -U tradingai -d tradingai -c \
  "SELECT 'decision_records' t, count(*) FROM decision_records
   UNION ALL SELECT 'trades', count(*) FROM trades;"

# 5. start the app
cd /docker/tradingai && docker compose start api web
```

`pg_restore` prints warnings about extensions it cannot recreate as a
non-superuser. Those are expected and harmless — the row counts in step 4 are
what tell you whether the restore worked.

## Restore one table (e.g. only the decision records)

The dumps are custom-format precisely so this is possible — you rarely want to
overwrite everything to recover one thing.

```bash
docker exec -i tradingai-db-1 pg_restore -U tradingai -d tradingai \
  --no-owner --data-only --table=decision_records \
  < ~/tradingai-backups/<TIMESTAMP>/database.dump
```

## Restore the dominance history

Not in the database — plain CSVs, and the one thing here that genuinely cannot
be regenerated. No source sells intraday dominance history; it exists only
because something was recording at the time.

```bash
# stop the collector so it is not appending while you replace the file
docker stop cft-bridge 2>/dev/null   # unrelated, ignore
docker stop tradingai-dominance-collector-1

# the collector appends, so a newer file may hold rows the backup does not.
# Compare before overwriting — never restore over a longer series.
wc -l ~/tradingai-backups/<TIMESTAMP>/dominance/dominance_intraday_raw.csv
wc -l /opt/dominance/dominance_intraday_raw.csv

docker run --rm -v /opt/dominance:/t \
  -v ~/tradingai-backups/<TIMESTAMP>/dominance:/b:ro alpine:3 \
  cp /b/dominance_intraday_raw.csv /t/

docker start tradingai-dominance-collector-1
```

## What these backups do NOT protect against

Stated plainly so nobody assumes more coverage than exists:

* **Loss of the VPS itself.** Backups sit on the same host as the database. They
  survive database corruption, a dropped table, a bad migration, or a deleted
  Docker volume — not the machine going away. Off-site copies are tracked in
  `KNOWN_ISSUES.md`.
* **Anything since the last run.** Backups are daily at 03:15 UTC, so worst case
  is ~24h of trades and decisions. Take a manual one before anything risky:
  `ssh pfe-vps '~/tradingai-backups/backup.sh'`
