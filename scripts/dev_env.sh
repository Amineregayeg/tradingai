#!/usr/bin/env bash
#
# Build a local environment that can run the test suites (KNOWN_ISSUES B7).
#
# WHY THIS EXISTS
# For most of this project the ONLY way to run 632 backend tests was to commit,
# push, and wait ~4 minutes for CI. That is not merely slow — it changes what
# gets verified. Two real bugs (a diagnostic string that degraded to "<lambda>"
# under patching, and Docker Compose silently eating "${GIT_REF}") had to be
# caught with hand-written throwaway probes, because writing a test and running
# it was not an available move.
#
# IT DELIBERATELY MIRRORS CI, NOT A CONVENIENT LOCAL SETUP
# The backend installs with `pip install -e ".[dev]"` — the same command CI
# runs, which resolves dependencies through pyproject.toml's dynamic metadata
# rather than reading requirements files directly. Installing "the easy way"
# here would let that wiring break without anyone noticing until the next
# person tried it. It has broken before (an unsatisfiable numpy pin).
#
# TWO PLACEMENT DECISIONS THAT MATTER ON WSL
#   * The venv goes in $HOME, not the repo. The repo lives on /mnt/c, a 9p
#     filesystem where a venv's thousands of small files are painfully slow.
#   * pip is bootstrapped with get-pip.py rather than ensurepip. Debian strips
#     ensurepip out of the stock python, and the alternative is asking for a
#     sudo password to install python3-venv — root access this needs no part of.
#
# USAGE
#   ./scripts/dev_env.sh          # set everything up (idempotent)
#   ./scripts/dev_env.sh --check  # report what is present, change nothing

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${TRADINGAI_VENV:-$HOME/.venvs/tradingai}"
CHECK_ONLY="${1:-}"

say() { printf '%s\n' "$*"; }
ok()  { printf '  ok    %s\n' "$*"; }
bad() { printf '  MISS  %s\n' "$*"; }

# ---------------------------------------------------------------------------
# --check: report only
# ---------------------------------------------------------------------------
if [[ "$CHECK_ONLY" == "--check" ]]; then
  say "Backend:"
  [[ -x "$VENV/bin/python" ]] && ok "venv at $VENV" || bad "no venv — run $0"
  if [[ -x "$VENV/bin/python" ]] && "$VENV/bin/python" -c 'import pytest' 2>/dev/null; then
    ok "pytest $("$VENV/bin/python" -m pytest --version 2>&1 | head -1 | awk '{print $2}')"
  else
    bad "pytest not installed"
  fi
  say "Frontend:"
  command -v node >/dev/null && ok "node $(node -v)" || bad "node not installed"
  command -v pnpm >/dev/null && ok "pnpm $(pnpm -v)" || bad "pnpm not installed"
  # Checks for the RUNNER, not the directory. `[ -d node_modules ]` is true for
  # an empty directory — which is exactly what a half-finished pnpm install
  # leaves behind, and it reported "present" while `vitest` was still missing.
  if [[ -x "$REPO/frontend/node_modules/.bin/vitest" ]]; then
    ok "frontend deps installed (vitest present)"
  else
    bad "frontend deps incomplete — vitest not found"
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------
say "==> Backend environment at $VENV"

if [[ ! -x "$VENV/bin/python" ]]; then
  mkdir -p "$(dirname "$VENV")"
  python3 -m venv "$VENV" || true   # succeeds without pip on Debian; that is handled below
fi

if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
  say "    bootstrapping pip (ensurepip is absent on Debian's python)"
  tmp="$(mktemp -d)"
  curl -sSL -o "$tmp/get-pip.py" https://bootstrap.pypa.io/get-pip.py
  "$VENV/bin/python" "$tmp/get-pip.py" -q
  rm -rf "$tmp"
fi
ok "pip $("$VENV/bin/python" -m pip --version | awk '{print $2}')"

say "    installing (the same command CI runs)"
( cd "$REPO/backend" && "$VENV/bin/pip" install -q -e ".[dev]" )

# The check CI performs, repeated here. Test tooling that drags in a different
# numpy/pandas than production means a green suite about the wrong system.
"$VENV/bin/python" - "$REPO" <<'PY'
import re, sys
from importlib.metadata import version, PackageNotFoundError

want = {}
with open(f"{sys.argv[1]}/backend/requirements-prod.txt") as fh:
    for line in fh:
        line = line.split("#")[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?==(.+)$", line)
        if m:
            want[m.group(1).lower()] = m.group(2)

bad = []
for pkg in ("numpy", "pandas", "smartmoneyconcepts", "pandas-ta"):
    expected = want.get(pkg)
    try:
        got = version(pkg)
    except PackageNotFoundError:
        got = None
    if expected and got == expected:
        print(f"  ok    {pkg} {got} matches production")
    else:
        print(f"  DRIFT {pkg}: installed {got}, production wants {expected}")
        bad.append(pkg)
if bad:
    sys.exit(f"  strategy-critical versions differ from production: {', '.join(bad)}")
PY

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
say "==> Frontend"
if command -v pnpm >/dev/null && command -v node >/dev/null; then
  ok "node $(node -v), pnpm $(pnpm -v)"
  # CI pins node 20 to match the web container. A newer local node is usually
  # fine for vitest but is NOT proof the production build works — CI remains the
  # authority on that.
  major="$(node -v | sed 's/^v\([0-9]*\).*/\1/')"
  [[ "$major" != "20" ]] && say "    note: CI and production use node 20; this box has $(node -v)"
  ( cd "$REPO/frontend" && pnpm install --frozen-lockfile --silent )
  ok "frontend dependencies installed"
else
  bad "node and/or pnpm missing — frontend tests cannot run here"
fi

cat <<EOF

Ready. To run things:

  Backend suite      $VENV/bin/python -m pytest            (run from backend/)
  One file           $VENV/bin/python -m pytest tests/unit/test_build_info.py
  Frontend tests     pnpm exec vitest run                  (run from frontend/)
  Frontend types     pnpm tsc
  Lookahead guards   ./scripts/verify_guards.sh            (run from backend/)

Note: 'pnpm test' is bare 'vitest', which watches forever. Use 'vitest run'.
EOF
