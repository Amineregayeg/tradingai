#!/usr/bin/env bash
#
# Protect `main` so a red build cannot be merged (KNOWN_ISSUES D3).
#
# WHY THIS IS A SCRIPT AND NOT A CHECKLIST
# Branch protection is configured by NAME. If a required check is named
# something no job actually reports, GitHub waits forever for it and `main`
# becomes permanently unmergeable — by everyone, with no obvious cause. A
# checklist invites a typo; renaming a CI job silently arms the same trap.
# So this script REFUSES to apply anything until it has confirmed every name
# it is about to require was reported by a real run.
#
# WHAT THIS CHANGES ABOUT DAY-TO-DAY WORK
# Required status checks apply to direct pushes too, not only merges. A fresh
# commit has no checks yet, so `git push origin main` starts being rejected.
# Work moves to: branch -> push -> open a PR -> CI goes green -> merge.
# That is the point — it is also the whole cost. Decide you want it before
# running this.
#
# USAGE
#   GITHUB_TOKEN=<a token with ADMIN on the repo> ./scripts/enable_branch_protection.sh
#
# A token with only `push` cannot do this; GitHub reports that as a confusing
# 404 ("Not Found") rather than 403, which is checked for and explained below.
#
# TO UNDO / ESCAPE
# If CI itself breaks and nobody can merge the fix, remove protection with:
#   curl -X DELETE -H "Authorization: token $GITHUB_TOKEN" \
#     https://api.github.com/repos/Amineregayeg/tradingai/branches/main/protection
# Re-run this script afterwards. That escape hatch is written down on purpose:
# an emergency is exactly when nobody wants to be reverse-engineering the API.

set -euo pipefail

REPO="${REPO:-Amineregayeg/tradingai}"
BRANCH="${BRANCH:-main}"
API="https://api.github.com/repos/${REPO}"

# The four CI jobs, spelled exactly as they report. Verified against a real run
# below rather than trusted.
REQUIRED_CHECKS=(
  "Dependency versions have one source of truth"
  "Backend suite (production pins)"
  "Tier 0.2 - lookahead guards must bite"
  "Frontend typecheck / test / build"
)

# Should admins be bound by the rule too?
#
# `true` means protection is real: nobody bypasses, including the repo owner.
# `false` leaves a silent hole — the one person most likely to be merging is
# also the one who can ignore the gate, which makes the badge say "protected"
# while the property does not hold. Default to honest; the escape hatch above
# covers the emergency this would otherwise create.
ENFORCE_ADMINS="${ENFORCE_ADMINS:-true}"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "GITHUB_TOKEN is not set. It must be a token with ADMIN on ${REPO}." >&2
  exit 1
fi

auth=(-H "Authorization: token ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json")

# --------------------------------------------------------------------------
# 1. Confirm the token can actually do this, before changing anything.
# --------------------------------------------------------------------------
echo "==> Checking permissions on ${REPO}"
admin=$(curl -fsS "${auth[@]}" "${API}" |
  python3 -c 'import sys,json; print(json.load(sys.stdin)["permissions"].get("admin"))')
if [[ "${admin}" != "True" ]]; then
  cat >&2 <<'MSG'
This token does not have admin on the repository, so it cannot set branch
protection. GitHub reports this as "Not Found", not as a permission error.

Use a token belonging to someone with the Admin role, or have them run this.
MSG
  exit 1
fi
echo "    admin: yes"

# --------------------------------------------------------------------------
# 2. Verify every name we are about to require is one a real run reports.
#    This is the step that prevents a permanently unmergeable branch.
# --------------------------------------------------------------------------
echo "==> Verifying check names against the latest ${BRANCH} run"
run_id=$(curl -fsS "${auth[@]}" "${API}/actions/runs?branch=${BRANCH}&per_page=1" |
  python3 -c 'import sys,json; r=json.load(sys.stdin)["workflow_runs"]; print(r[0]["id"] if r else "")')
if [[ -z "${run_id}" ]]; then
  echo "No workflow run found on ${BRANCH}; cannot verify names. Aborting." >&2
  exit 1
fi

reported=$(curl -fsS "${auth[@]}" "${API}/actions/runs/${run_id}/jobs" |
  python3 -c 'import sys,json; [print(j["name"]) for j in json.load(sys.stdin)["jobs"]]')

missing=0
for check in "${REQUIRED_CHECKS[@]}"; do
  if grep -Fxq "${check}" <<<"${reported}"; then
    echo "    ok      ${check}"
  else
    echo "    MISSING ${check}" >&2
    missing=1
  fi
done
if [[ "${missing}" -eq 1 ]]; then
  cat >&2 <<MSG

One or more required checks are not reported by any job in run ${run_id}.
Requiring them would block every merge to ${BRANCH} indefinitely.

Job names actually reported:
${reported}

Fix REQUIRED_CHECKS in this script to match, then re-run.
MSG
  exit 1
fi

# --------------------------------------------------------------------------
# 3. Apply.
# --------------------------------------------------------------------------
echo "==> Applying protection to ${BRANCH} (enforce_admins=${ENFORCE_ADMINS})"
payload=$(ENFORCE_ADMINS="${ENFORCE_ADMINS}" python3 - "${REQUIRED_CHECKS[@]}" <<'PY'
import json, os, sys
print(json.dumps({
    "required_status_checks": {
        # strict = the branch must be up to date with main before merging.
        # Without this, two branches that each pass CI alone can still break
        # main once combined, which is the failure this whole exercise is about.
        "strict": True,
        "contexts": sys.argv[1:],
    },
    "enforce_admins": os.environ["ENFORCE_ADMINS"] == "true",
    # Deliberately no review requirement: the gate being added here is "CI must
    # be green", not "a human must sign off". Requiring approvals on a
    # three-person team mostly means waiting. Add it later if wanted; it is a
    # separate decision from D3.
    "required_pull_request_reviews": None,
    "restrictions": None,
    # A force-push to main rewrites history that CI already judged, which makes
    # every green check above meaningless. Deletion likewise.
    "allow_force_pushes": False,
    "allow_deletions": False,
}))
PY
)

http=$(curl -sS -o /tmp/bp_resp.json -w '%{http_code}' -X PUT "${auth[@]}" \
  "${API}/branches/${BRANCH}/protection" -d "${payload}")
if [[ "${http}" != "200" ]]; then
  echo "Failed (HTTP ${http}):" >&2
  cat /tmp/bp_resp.json >&2
  exit 1
fi

# --------------------------------------------------------------------------
# 4. Read it back. Applying and verifying are not the same thing.
# --------------------------------------------------------------------------
echo "==> Verifying what is now in effect"
curl -fsS "${auth[@]}" "${API}/branches/${BRANCH}/protection" | python3 -c '
import sys, json
p = json.load(sys.stdin)
print("    required checks:")
for c in p["required_status_checks"]["contexts"]:
    print(f"      - {c}")
print("    strict (branch must be current):", p["required_status_checks"]["strict"])
print("    enforced for admins:", p["enforce_admins"]["enabled"])
print("    force pushes allowed:", p["allow_force_pushes"]["enabled"])
print("    deletions allowed:", p["allow_deletions"]["enabled"])
'
echo
echo "Done. Direct pushes to ${BRANCH} will now be rejected — use a branch and a PR."
