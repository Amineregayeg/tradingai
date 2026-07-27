#!/usr/bin/env bash
#
# TIER 0.2 META-CHECK — "reverting a guard MUST fail a test"
#
# acceptance_criteria.yaml states Tier 0.2 as:
#     "pytest ... green; reverting a guard MUST fail a test"
#
# The first half is an ordinary test run. The second half is a claim ABOUT the
# test suite that no test inside that suite can make about itself: a green suite
# proves the guards are present, not that they are load-bearing. A test can rot
# into passing vacuously — the fixture stops producing the setup, a library
# changes shape, an assertion silently matches nothing — and you would never see
# it, because green looks identical either way.
#
# So this script mutates each lookahead guard back to its known-buggy form and
# asserts the suite goes RED. A guard whose removal changes nothing is not a
# guard; it is a comment.
#
# Run locally from backend/:  bash scripts/verify_guards.sh
# CI runs it on every push (.github/workflows/ci.yml).
#
# Exit 0 = every guard is load-bearing. Exit 1 = at least one is not.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 1   # -> backend/

ENGINE="app/services/backtest/engine.py"
FAILED=0

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "ERROR: not a git repo — this script restores mutated files via git checkout."
  exit 1
fi

restore() { git checkout -- "$ENGINE" 2>/dev/null || true; }
# Restore on ANY exit path, including Ctrl-C or an unexpected failure, so a
# mutated engine can never be left behind in a working tree or a CI cache.
trap restore EXIT INT TERM

if ! git diff --quiet -- "$ENGINE"; then
  echo "ERROR: $ENGINE has uncommitted changes. Commit or stash them first —"
  echo "       this script overwrites that file and would destroy your work."
  exit 1
fi

# probe <name> <sed-expression> <test-path> <what-the-guard-prevents>
probe() {
  local name="$1" expr="$2" tests="$3" prevents="$4"

  restore
  sed -i "$expr" "$ENGINE"

  # If the mutation did not change the file, the guard has been refactored or
  # renamed and this probe is now testing nothing. That is a FAILURE, not a
  # pass — a silently-inert probe is exactly the rot this script exists to catch.
  if git diff --quiet -- "$ENGINE"; then
    echo "FAIL  $name"
    echo "      The mutation matched nothing in $ENGINE."
    echo "      The guard was moved/renamed and this probe is now inert."
    echo "      Fix the sed expression in scripts/verify_guards.sh to match the new code."
    FAILED=1
    restore
    return
  fi

  if AUTH_DISABLED=true python -m pytest -q -p no:cacheprovider "$tests" >/dev/null 2>&1; then
    echo "FAIL  $name"
    echo "      Reverted the guard and $tests STILL PASSES."
    echo "      Nothing is defending against: $prevents"
    FAILED=1
  else
    echo "ok    $name — reverting it turns $tests red"
  fi

  restore
}

echo "Tier 0.2 — verifying each lookahead guard is load-bearing"
echo "-------------------------------------------------------------------"

probe "FVG entry admissible only from born+2" \
      's/if (i - c\["born"\]) < 2:/if (i - c["born"]) < 1:/' \
      "tests/integration/test_lookahead_regression.py" \
      "filling at a bar's own extreme (the smc near-edge is low.shift(-1), so at born+1 the retrace test is vacuously true)"

probe "daily bias built from the causal trailing window" \
      's/bias_events = _causal_daily_bias_events(bias_df, p.swing_length)/bias_events = _daily_bias_events(bias_df, p.swing_length)/' \
      "tests/integration/test_bias_causality.py" \
      "trade direction chosen using bars that had not happened yet"

echo "-------------------------------------------------------------------"

# KNOWN GAP — not yet a probe, because no test covers it.
#
# app/services/live/strategy_step.py carries the same born+2 guard as the
# backtest ("if not (2 <= i - born <= p.fvg_lookback)"), but NO test exercises
# the live entry brain's causality. Mutating it would prove only that the gap
# exists, so it is reported here rather than failing the build.
#
# This matters more than it looks: strategy_step.py is the path that trades. It
# also still calls the NON-causal _daily_bias_events, so the live engine and the
# backtest are running different decision rules today.
#
# TO CLOSE: add tests/integration/test_live_step_causality.py asserting that
# evaluate_latest_bar never returns a Signal whose entry equals the deciding
# bar's own high/low, then add a probe for it above.
echo "NOTE  strategy_step.py (the LIVE entry brain) has no causality test."
echo "      Its guard is therefore unverified. See the comment in this script."

if [ "$FAILED" -ne 0 ]; then
  echo ""
  echo "TIER 0.2 FAILED — at least one lookahead guard is not load-bearing."
  exit 1
fi

echo ""
echo "TIER 0.2 PASSED — every probed guard is load-bearing."
