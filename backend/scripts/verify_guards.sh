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
DOMINANCE="app/services/market_data/sources/dominance.py"
EXECUTION="app/services/execution/service.py"
RESOLVE="app/services/live/crypto_loop.py"
GUARDED_FILES=("$ENGINE" "$DOMINANCE" "$EXECUTION" "$RESOLVE")
FAILED=0

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "ERROR: not a git repo — this script restores mutated files via git checkout."
  exit 1
fi

# THE RUNNER MUST WORK, AND THE BASELINE MUST BE GREEN.
#
# This script reads "the mutated test run failed" as "the guard bit". A shell
# returns 127 for a command that does not exist, which is also a failure — so on
# a machine without `python` on PATH, EVERY probe reported ok and the script
# printed "TIER 0.2 PASSED" without having run a single test. Vacuously green,
# in the script whose entire purpose is catching vacuously-green checks.
#
# The same hole swallows a baseline that is red for unrelated reasons: if the
# test already fails before mutation, its failure after mutation proves nothing.
# So both are checked up front, and neither is recoverable — there is no useful
# partial result once the instrument is untrustworthy.
PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  for cand in python python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import pytest' >/dev/null 2>&1; then
      PYTHON="$cand"; break
    fi
  done
fi
if [[ -z "$PYTHON" ]] || ! "$PYTHON" -m pytest --version >/dev/null 2>&1; then
  echo "ERROR: no working python with pytest was found."
  echo "       Tried: python, python3. Set PYTHON=/path/to/python to override,"
  echo "       or run ./scripts/dev_env.sh from the repo root to build one."
  echo "       Refusing to continue: without a runner every probe would report"
  echo "       'ok' because a missing command looks exactly like a failing test."
  exit 2
fi

#: Every test path any probe uses. probe() asserts its own path is listed here,
#: so this cannot drift out of step with the probes below.
BASELINE_TESTS=(
  "tests/integration/test_bias_causality.py"
  "tests/integration/test_lookahead_regression.py"
  "tests/integration/test_settle_persist_resolve_adv.py"
  "tests/unit/test_dominance_source.py"
  "tests/unit/test_execution_fill_sizing.py"
)

# RESTORE ONLY WHAT THIS RUN CHANGED. The promise used to be wider, and the width
# was the bug (KNOWN_ISSUES B18).
#
# `restore` is a git checkout of the guarded files, which destroys any uncommitted
# work in them. It ran on EVERY exit path — including the pre-flight refusals
# below, whose entire purpose is to protect uncommitted work. So the script
# printed "would destroy your work" and then destroyed it, in the same breath,
# leaving no dirty file, no stash and no reflog entry to recover from. The message
# was the dangerous part: it reads as proof you were protected, so the one person
# able to notice is the one being told not to look.
#
# A plain global, deliberately: the EXIT trap runs in the shell's own context and
# must see it. Never `local`, never assigned inside a subshell or a pipeline — a
# flag the trap cannot see makes restore a permanent no-op, mutations then stack
# across probes, and the inert-sed check at :123 defeats itself because the file
# already differs from HEAD. That failure prints eight `ok` lines and exits 0,
# byte-identical to a real pass. `git status --porcelain` after a run is the only
# thing that tells the two apart.
MUTATED=0
restore() {
  [[ "$MUTATED" -eq 1 ]] || return 0
  git checkout -- "${GUARDED_FILES[@]}" 2>/dev/null || true
}
# Still restores on ANY exit path once a mutation exists — including Ctrl-C or an
# unexpected failure — so a mutated file can never be left behind in a working
# tree or a CI cache. What changed is that exits taken BEFORE the first mutation
# now have nothing to undo, which is what this comment always claimed.
trap restore EXIT INT TERM

for f in "${GUARDED_FILES[@]}"; do
  # An UNTRACKED file cannot be restored by `git checkout --`, so mutating it
  # would leave the mutation in place permanently. (This bit during development:
  # three probes silently accumulated in a new file because rollback no-oped.)
  if ! git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
    echo "ERROR: $f is not tracked by git."
    echo "       This script mutates it and restores via git checkout, which"
    echo "       cannot restore an untracked file. Commit it first."
    exit 1
  fi
  if ! git diff --quiet -- "$f"; then
    echo "ERROR: $f has uncommitted changes. Commit or stash them first —"
    echo "       this script overwrites that file and would destroy your work."
    exit 1
  fi
done

# probe <name> <file> <sed-expression> <test-path> <what-the-guard-prevents>
probe() {
  local name="$1" file="$2" expr="$3" tests="$4" prevents="$5"

  # Keeps BASELINE_TESTS honest: a probe pointing at a file the baseline never
  # proved green would be trusting an unverified instrument.
  local listed=0 t
  for t in "${BASELINE_TESTS[@]}"; do [[ "$t" == "$tests" ]] && listed=1; done
  if [[ "$listed" -eq 0 ]]; then
    echo "FAIL  $name"
    echo "      $tests is not in BASELINE_TESTS, so it was never checked green"
    echo "      before mutation. Add it there in scripts/verify_guards.sh."
    FAILED=1
    return
  fi

  restore
  # BEFORE the sed, never after. A kill between the two would otherwise leave a
  # mutated source file with restore disabled — a mutation persisting silently
  # into a working tree or a CI cache, which is the exact catastrophe this trap
  # exists for and strictly worse than the data loss B18 describes. Setting it
  # ahead of a sed that then matches nothing costs nothing: `git checkout` of an
  # unmodified file is a no-op.
  MUTATED=1
  sed -i "$expr" "$file"

  # If the mutation did not change the file, the guard has been refactored or
  # renamed and this probe is now testing nothing. That is a FAILURE, not a
  # pass — a silently-inert probe is exactly the rot this script exists to catch.
  if git diff --quiet -- "$file"; then
    echo "FAIL  $name"
    echo "      The mutation matched nothing in $file."
    echo "      The guard was moved/renamed and this probe is now inert."
    echo "      Fix the sed expression in scripts/verify_guards.sh to match the new code."
    FAILED=1
    restore
    return
  fi

  if AUTH_DISABLED=true "$PYTHON" -m pytest -q -p no:cacheprovider "$tests" >/dev/null 2>&1; then
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
echo "baseline: $PYTHON $("$PYTHON" -m pytest --version 2>&1 | head -1)"
if ! AUTH_DISABLED=true "$PYTHON" -m pytest -q -p no:cacheprovider \
     "${BASELINE_TESTS[@]}" >/dev/null 2>&1; then
  echo "ERROR: the probed tests are RED before any mutation."
  echo "       Every probe would then report 'ok' for the wrong reason — a test"
  echo "       that already fails cannot demonstrate that removing a guard is"
  echo "       what broke it. Fix the suite first:"
  printf '         %s\n' "${BASELINE_TESTS[@]}"
  exit 2
fi
echo "ok    baseline green — mutations are measured against a working suite"
echo "-------------------------------------------------------------------"

probe "FVG entry admissible only from born+2" "$ENGINE" \
      's/if (i - c\["born"\]) < 2:/if (i - c["born"]) < 1:/' \
      "tests/integration/test_lookahead_regression.py" \
      "filling at a bar's own extreme (the smc near-edge is low.shift(-1), so at born+1 the retrace test is vacuously true)"

probe "daily bias built from the causal trailing window" "$ENGINE" \
      's/bias_events = _causal_daily_bias_events(bias_df, p.swing_length)/bias_events = _daily_bias_events(bias_df, p.swing_length)/' \
      "tests/integration/test_bias_causality.py" \
      "trade direction chosen using bars that had not happened yet"

# Dominance bars feed Magic Alignment's confirmation signal. A lookahead here is
# harder to notice than one in the entry logic and just as capable of inventing
# an edge, so the same standard applies.
probe "dominance bars close on their left edge" "$DOMINANCE" \
      's/label="left", closed="left"/label="left", closed="right"/' \
      "tests/unit/test_dominance_source.py" \
      "a dominance bar absorbing a sample from after its own period closed"

probe "dominance partial trailing bar dropped" "$DOMINANCE" \
      's/if last_sample < period_end:/if False:/' \
      "tests/unit/test_dominance_source.py" \
      "confirming an entry against a still-forming dominance bar"

# The pattern tracks the line's TEXT, which changed when the gap bug was fixed: the
# drop is now scoped with `subset=price_cols`, because `samples` is 0 rather than
# NaN for an empty period, so a bare `how="all"` matched nothing and this probe was
# mutating a line that did nothing. The line it targets never moved; only its
# spelling did. See KNOWN_ISSUES B23 — nothing detects the inert case.
probe "dominance gaps stay gaps" "$DOMINANCE" \
      's/bars = bars.dropna(subset=price_cols, how="all")/bars = bars.ffill()/' \
      "tests/unit/test_dominance_source.py" \
      "flat synthetic candles across a collector outage, which read as real structure"

# risk_pct is pre-registered and frozen so that risk is a CONSTANT. Sizing a
# market order from a price it will not fill at turns it back into a variable
# that nothing measures, which is a Tier-0 problem wearing execution clothes.
probe "market orders sized from the real fill price" "$EXECUTION" \
      's/            sizing_price = mark/            sizing_price = sig.entry/' \
      "tests/unit/test_execution_fill_sizing.py" \
      "risking more or less than risk_pct depending on which way price drifted before the order"

probe "entry refused once price is through the stop" "$EXECUTION" \
      's/            if (long and mark <= sig.sl) or (not long and mark >= sig.sl):/            if False:/' \
      "tests/unit/test_execution_fill_sizing.py" \
      "opening a position already beyond its own stop — a guaranteed instant loss"

probe "realized R measured against the fill, not the ask" "$RESOLVE" \
      's/                entry = float(fill if fill is not None else (rec.signal_entry or 0))/                entry = float(rec.signal_entry or 0)/' \
      "tests/integration/test_settle_persist_resolve_adv.py" \
      "every R (and every gap_r the feedback loop reads) being off by the fill drift"

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
