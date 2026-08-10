#!/usr/bin/env bash
#
# Deploy the intraday dominance collector.
#
#     ./scripts/deploy_dominance.sh              # deploy if the server differs
#     ./scripts/deploy_dominance.sh --check      # report, change nothing
#     ./scripts/deploy_dominance.sh --force      # recreate even if nothing differs
#
# THIS DEPLOYS COMPOSE, NOT CODE. READ THIS BEFORE ASSUMING A FIX IS LIVE.
# Two different things reach the container by two different routes, and only one of
# them is in this repo's working tree:
#
#   * The COMPOSE FILE — including the `--loop` cadence — is copied from
#     deploy/compose.dominance.yaml by this script. It goes live on this run, from
#     whatever branch you are standing on.
#   * collect_dominance.py — the collector ITSELF — is not copied at all. The
#     container `git clone`s it from GitHub at startup. So a change to that script
#     reaches production only once it is merged and the container is recreated
#     AGAIN. Deploying from a feature branch ships the new compose against the old
#     code, silently and by design.
#
# This script prints the ref and sha it will clone before recreating, so that
# distinction is visible at deploy time instead of being discovered later. It is the
# same shape as the failure that created this script: a value committed, believed
# deployed, and running at its old setting for six days.
#
# WHY THIS EXISTS
# The collector had no deploy path at all. It is compose project
# `tradingai-dominance`, living at /home/deploy/tradingai-dominance/compose.yaml on
# the VPS — a hand-copied file outside the `tradingai` stack, mentioned in no runbook
# and recreated by no documented command. A grep for "dominance" or "collector"
# across agents/PROMPT_EXECUTE.md and the deploy runbook returned nothing.
#
# The result was predictable and it happened: `--loop 15` was committed on
# 2026-08-06, KNOWN_ISSUES B11 recorded the sampling-rate fix as DONE, and the
# container went on sampling at 60s for six more days because nothing ever copied
# the file or recreated the container. Nobody was careless. There was no step to skip.
#
# So: one committed command, which copies the repo's compose to the server, recreates
# only the collector, and then proves the result with check_deploy_drift.py rather
# than announcing success. The cadence is read OUT of the compose file rather than
# written here, so this script cannot become a third place the number has to agree.
#
# WHAT IT DELIBERATELY DOES NOT TOUCH
# `api`, `web` and the database are compose project `tradingai` at /docker/tradingai/,
# a different project entirely. This script names its project and its single service
# explicitly and can therefore never recreate the api — which matters, because
# recreating the api kills the live engine mid-run and abandons any open position
# (KNOWN_ISSUES B14, and the ETH position destroyed that way on 2026-08-08).
#
# ONE THING IT CANNOT DO, STATED SO NOBODY ASSUMES OTHERWISE
# The container `git clone`s backend/scripts/ from GitHub **main** at startup. So this
# script deploys the CADENCE (which lives in the compose command) immediately, but any
# change to collect_dominance.py itself only reaches production once it is merged to
# main and the container is recreated again. It says so at the end of every run.
set -euo pipefail

HOST="${DOMINANCE_HOST:-pfe-vps}"
PROJECT="tradingai-dominance"
SERVICE="collector"
CONTAINER="${PROJECT}-${SERVICE}-1"
REMOTE="/home/deploy/tradingai-dominance/compose.yaml"

cd "$(dirname "$0")/.."
LOCAL="deploy/compose.dominance.yaml"
PYTHON="${PYTHON:-$HOME/.venvs/tradingai/bin/python}"

MODE=deploy
case "${1:-}" in
  --check) MODE=check ;;
  --force) MODE=force ;;
  "") ;;
  *) echo "usage: $0 [--check|--force]" >&2; exit 2 ;;
esac

[[ -f "$LOCAL" ]] || { echo "FATAL: $LOCAL not found (run from anywhere in the repo)" >&2; exit 2; }
[[ -x "$PYTHON" ]] || { echo "FATAL: no python at $PYTHON — set PYTHON=" >&2; exit 2; }

# The cadence the repo intends, read from the file being deployed. Never hardcoded:
# a second copy of this number is how the first one went stale.
CADENCE="$(grep -oE 'collect_dominance\.py --loop [0-9]+' "$LOCAL" | grep -oE '[0-9]+$' || true)"
[[ -n "$CADENCE" ]] || { echo "FATAL: no '--loop N' found in $LOCAL" >&2; exit 2; }

# What the container will CLONE, as opposed to what this script COPIES. Read out of
# the compose file rather than assumed, then resolved against the real remote — the
# whole point is that these two can differ from your working tree without saying so.
CLONE_URL="$(grep -oE 'git clone[^\n]*https://[^ ]+' "$LOCAL" | grep -oE 'https://[^ ]+' | head -1 || true)"
CLONE_REF="$(grep -oE 'git clone.*--branch[= ]([^ ]+)' "$LOCAL" | sed -E 's/.*--branch[= ]([^ ]+).*/\1/' || true)"
CLONE_REF="${CLONE_REF:-main}"   # no --branch in the clone ⇒ the remote's default
CLONE_SHA="$(git ls-remote "$CLONE_URL" "$CLONE_REF" 2>/dev/null | cut -f1 || true)"
LOCAL_HEAD="$(git rev-parse HEAD)"
LOCAL_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

echo "host      $HOST"
echo "project   $PROJECT   service $SERVICE"
echo "file      $LOCAL  ->  $REMOTE      (COPIED from this branch)"
echo "cadence   --loop $CADENCE (read from $LOCAL)"
echo "code      $CLONE_URL @ $CLONE_REF"
echo "          -> ${CLONE_SHA:-UNKNOWN (could not reach the remote)}   (CLONED by the container)"
echo "you are   $LOCAL_BRANCH @ $LOCAL_HEAD"
if [[ -n "$CLONE_SHA" && "$CLONE_SHA" != "$LOCAL_HEAD" ]]; then
  echo
  echo "NOTE: the container will clone $CLONE_REF, which is NOT your checkout."
  echo "      Changes to backend/scripts/collect_dominance.py in this branch will NOT"
  echo "      be live after this deploy. The compose file — and so the cadence — will."
fi
echo

# ---------------------------------------------------------------------------
# What is out there now
remote_file="$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "cat $REMOTE" 2>/dev/null || true)"
[[ -n "$remote_file" ]] || { echo "FATAL: could not read $REMOTE on $HOST" >&2; exit 1; }

running_cmd="$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" \
  "docker inspect $CONTAINER --format '{{json .Config.Cmd}}' 2>/dev/null" || true)"

file_matches=no
diff <(printf '%s\n' "$remote_file") "$LOCAL" >/dev/null 2>&1 && file_matches=yes
container_matches=no
[[ "$running_cmd" == *"--loop $CADENCE"* ]] && container_matches=yes

echo "server file matches repo   $file_matches"
echo "running container cadence  $container_matches (--loop $CADENCE)"
echo

if [[ "$MODE" == check ]]; then
  [[ "$file_matches" == yes && "$container_matches" == yes ]] && { echo "in sync"; exit 0; }
  echo "OUT OF SYNC — run without --check to deploy"; exit 1
fi

# Idempotent by intent, not just by accident. A needless recreate puts a real gap in a
# series that cannot be backfilled, so "nothing to do" must actually do nothing.
if [[ "$MODE" != force && "$file_matches" == yes && "$container_matches" == yes ]]; then
  echo "already in sync — nothing to deploy (use --force to recreate anyway)"
  exit 0
fi

# ---------------------------------------------------------------------------
# Deploy
if [[ "$file_matches" == no ]]; then
  echo "backing up the current server file, then copying"
  ssh -o BatchMode=yes "$HOST" "cp -p $REMOTE $REMOTE.bak-\$(date -u +%Y%m%dT%H%M%SZ)"
  scp -q -o BatchMode=yes "$LOCAL" "$HOST:$REMOTE"
else
  echo "server file already matches; not copying"
fi

echo "recreating $SERVICE in project $PROJECT (and nothing else)"
ssh -o BatchMode=yes "$HOST" \
  "cd /home/deploy/tradingai-dominance && docker compose -p $PROJECT -f $REMOTE up -d --force-recreate $SERVICE"

# ---------------------------------------------------------------------------
# Prove it, rather than announce it
echo
echo "--- verifying ---"
after_cmd="$(ssh -o BatchMode=yes "$HOST" "docker inspect $CONTAINER --format '{{json .Config.Cmd}}'")"
if [[ "$after_cmd" != *"--loop $CADENCE"* ]]; then
  echo "FAIL: the running container is not on --loop $CADENCE:" >&2
  echo "$after_cmd" >&2
  exit 1
fi
echo "ok    running container is on --loop $CADENCE"
ssh -o BatchMode=yes "$HOST" "docker ps --filter name=$CONTAINER --format 'ok    {{.Status}}'"

echo
echo "--- check_deploy_drift.py ---"
if ! "$PYTHON" scripts/check_deploy_drift.py --host "$HOST"; then
  echo >&2
  echo "FAIL: drift remains after deploying. The repo still does not describe production." >&2
  exit 1
fi

cat <<EOF

Deployed. Two things this did NOT do, so nobody assumes otherwise:

  * collect_dominance.py itself is cloned from GitHub main at container start. Any
    change to that script reaches production only after it is merged to main AND the
    container is recreated again — this run picked up whatever main holds right now.
  * Samples already collected keep their old spacing. Only new ones are at ${CADENCE}s,
    and dominance history cannot be backfilled.

Confirm in the data (it needs a few minutes of samples to be meaningful):

  curl -s http://31.97.183.142:8097/dominance_intraday_raw.csv | tail -5
EOF
