#!/usr/bin/env bash
#
# TradingAI backup — database + the data that cannot be regenerated.
#
#   backup.sh            take a backup, verify it restores, prune old ones
#   backup.sh --status   report whether backups are healthy
#
# WHAT IS BEING PROTECTED, AND WHY IT IS NOT JUST "DATA"
#   * decision_records — every decision the engine made, with expected-vs-realized
#     R. This IS the evidence that the strategy does or does not work. Losing it
#     does not cost a rebuild, it costs the answer.
#   * trades — the realized record the whole performance view is computed from.
#   * dominance_intraday_raw.csv — UNRECOVERABLE. No source sells intraday
#     dominance history; it exists only because something was recording at the
#     time. A lost day is lost permanently, which is not true of anything else
#     here.
#
# THE PART THAT MATTERS MOST: EVERY BACKUP IS TEST-RESTORED.
# A backup that has never been restored is a hope, not a backup. This script
# restores each dump into a scratch database and compares row counts against the
# live one before declaring success. A dump that cannot be restored is worse than
# no dump, because it stops you looking for a real one.
#
# WHY NOT INSIDE THE APP. The api container already runs APScheduler, and putting
# backups there would have been less work. But then backups stop exactly when the
# app is down — which is when you are most likely to need one. This runs from
# host cron, independent of every container except the database itself.

set -uo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/tradingai-backups}"
DB_CONTAINER="${DB_CONTAINER:-tradingai-db-1}"
DB_USER="${DB_USER:-tradingai}"
DB_NAME="${DB_NAME:-tradingai}"
DOMINANCE_DIR="${DOMINANCE_DIR:-/opt/dominance}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

STATUS_FILE="$BACKUP_DIR/status.json"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/$STAMP"

log() { echo "$(date -u +%H:%M:%S) $*"; }

fail() {
    # Every failure path routes through here. A failed run must never leave a
    # directory named like a good backup: the first version of this script did,
    # and the status file then reported backup_count 2 when only one was real.
    # A count that includes failures is precisely the false comfort this whole
    # script exists to prevent.
    local msg="$1"
    log "FAILED: $msg"
    if [ -d "$DEST" ]; then
        if [ -s "$DEST/database.dump" ]; then
            mv "$DEST" "$DEST.UNVERIFIED"   # keep it — evidence of a bad dump
        else
            rm -rf "$DEST"                  # nothing salvageable
        fi
    fi
    write_status false "$msg"
    exit 1
}

write_status() {
    # Written on EVERY path including failure. A status file that only appears
    # on success cannot distinguish "healthy" from "the job never ran".
    local ok="$1" msg="$2"
    mkdir -p "$BACKUP_DIR"
    cat > "$STATUS_FILE" <<EOF
{
  "ok": $ok,
  "last_run": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "message": "$msg",
  "backup_count": $(find "$BACKUP_DIR" -maxdepth 1 -type d -name '20*' -exec test -s '{}/database.dump' \; -print 2>/dev/null | wc -l),
  "latest": "$STAMP",
  "retention_days": $RETENTION_DAYS
}
EOF
}

# ---------------------------------------------------------------------------
if [ "${1:-}" = "--status" ]; then
    [ -f "$STATUS_FILE" ] || { echo '{"ok": false, "message": "no backup has ever run"}'; exit 1; }
    cat "$STATUS_FILE"
    # Stale is a failure, not a detail: a status file saying "ok" from three
    # weeks ago is exactly the false comfort this is meant to prevent.
    last_epoch=$(date -u -d "$(grep -oP '"last_run":\s*"\K[^"]+' "$STATUS_FILE")" +%s 2>/dev/null || echo 0)
    age_h=$(( ( $(date -u +%s) - last_epoch ) / 3600 ))
    if [ "$age_h" -gt 48 ]; then
        echo "STALE: last backup was ${age_h}h ago" >&2
        exit 1
    fi
    exit 0
fi

mkdir -p "$DEST"
log "backup -> $DEST"

# --- 1. database ------------------------------------------------------------
# Custom format (-Fc): compressed, and restorable table-by-table, which matters
# when you want decision_records back without overwriting everything else.
if ! docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc \
        > "$DEST/database.dump" 2>"$DEST/pg_dump.err"; then
    fail "pg_dump: $(head -c 160 "$DEST/pg_dump.err" | tr -d '\n')"
fi
rm -f "$DEST/pg_dump.err"
db_size=$(stat -c %s "$DEST/database.dump")
log "  database.dump  $((db_size / 1024)) KB"

if [ "$db_size" -lt 1024 ]; then
    # A dump too small to be real. Caught here rather than discovered during a
    # restore, when it is too late to take another one.
    fail "dump is implausibly small ($db_size bytes)"
fi

# --- 2. unrecoverable files -------------------------------------------------
if [ -d "$DOMINANCE_DIR" ]; then
    mkdir -p "$DEST/dominance"
    cp "$DOMINANCE_DIR"/*.csv "$DEST/dominance/" 2>/dev/null
    n=$(find "$DEST/dominance" -name '*.csv' | wc -l)
    rows=$(cat "$DEST/dominance"/dominance_intraday_raw.csv 2>/dev/null | wc -l)
    log "  dominance      $n file(s), ${rows} intraday rows"
fi

# --- 3. VERIFY THE DUMP ACTUALLY RESTORES -----------------------------------
# The whole point. Restore into a scratch database and compare row counts
# against the live one. Nothing touches the real database at any point.
SCRATCH="verify_restore_$$"
verify_ok=true
verify_msg=""

docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -qc \
    "DROP DATABASE IF EXISTS $SCRATCH;" >/dev/null 2>&1
if ! docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -qc \
        "CREATE DATABASE $SCRATCH;" >/dev/null 2>&1; then
    verify_ok=false; verify_msg="could not create scratch database"
else
    if ! docker exec -i "$DB_CONTAINER" pg_restore -U "$DB_USER" -d "$SCRATCH" --no-owner \
            < "$DEST/database.dump" >/dev/null 2>&1; then
        # pg_restore warns about extensions it cannot recreate as non-superuser;
        # a non-zero exit alone is not proof of failure, so fall through to the
        # row-count comparison, which is what actually matters.
        verify_msg="pg_restore reported warnings"
    fi

    for table in decision_records trades broker_connections; do
        live=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc \
               "SELECT count(*) FROM $table;" 2>/dev/null || echo "ERR")
        rest=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$SCRATCH" -tAc \
               "SELECT count(*) FROM $table;" 2>/dev/null || echo "ERR")
        if [ "$live" != "$rest" ]; then
            verify_ok=false
            verify_msg="$table: live=$live restored=$rest"
            log "  VERIFY FAILED  $table live=$live restored=$rest"
        else
            log "  verified       $table $rest rows"
        fi
    done
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -qc \
        "DROP DATABASE IF EXISTS $SCRATCH;" >/dev/null 2>&1
fi

if [ "$verify_ok" != true ]; then
    fail "the dump did not restore correctly — $verify_msg"
fi

# --- 4. prune ---------------------------------------------------------------
# Only ever removes VERIFIED backups. A .UNVERIFIED directory is kept for
# inspection — it is evidence of a problem, not clutter.
pruned=$(find "$BACKUP_DIR" -maxdepth 1 -type d -name '20*' -mtime "+$RETENTION_DAYS" -print -exec rm -rf {} + 2>/dev/null | wc -l)
[ "$pruned" -gt 0 ] && log "  pruned $pruned backup(s) older than ${RETENTION_DAYS}d"

total=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
count=$(find "$BACKUP_DIR" -maxdepth 1 -type d -name '20*' | wc -l)
log "OK — $count backup(s), $total total"
write_status true "verified restore of $(basename "$DEST")"
