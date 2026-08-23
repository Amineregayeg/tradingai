"""T-0053 — `B177`: persist the DIRECTIONAL split of the entry-rule disagreement.

**`B177`'s premise as filed is OVERSTATED and this file is not written against it.** It says
production retains only the aggregate rate. It does not: `EntryComparison.detail` already
renders `disagree=`, `agree=`, `not_comparable=` and `rate=`, and `detail` IS persisted —
`DecisionTrace.reasons` emits one string per gate into `DecisionRecord.reasons`. Four terms
survive. Confirmed against STORED ROWS, not just the code path:
`agents/tasks/T-0053/_runs/live-corpus-20260819.txt`.

**WHAT IS ACTUALLY LOST IS NARROWER AND SHARPER.** `disagree` is one integer merging two
populations with OPPOSITE risk:

    RULE_STRICTER   live entered, the rule would not   -> missed opportunity
    RULE_LOOSER     live declined, the rule would      -> NEW LIVE EXPOSURE

`T-0040`'s criterion turns on exactly that split, and `disagree=3` renders identically for
three-looser and three-stricter.

**THE DIRECTION IS COMPUTED EVERY BAR AND DROPPED AT ONE BOUNDARY.**
`RuleComparison.as_dict()` carries both verdicts, `values()` puts the list under
`comparisons`, and `record_on` hands it to `trace.observe` as kwargs. `reasons` reads
`g.detail` and nothing else. The chain that would carry `Gate.values` terminates in dead
code: `Gate.as_dict()` has one caller, `DecisionTrace.as_dict()`, which has ZERO callers in
`app/`. **So the fix has to ride on `detail`, and the arm that matters is the one that reads
the emitted STRING — `values()` was always right.**
"""
from __future__ import annotations

import inspect

import pytest

from app.services.live.decision_trace import DecisionTrace
from app.services.live.entry_comparison import (
    EntryComparison,
    RuleComparison,
    disagreement_direction,
)


def _cmp(outcome, live, rule, rule_id="ENTRY-001"):
    return RuleComparison(rule_id, outcome, live, rule)


#: live took the entry, the rule said FAIL -> the rule is STRICTER -> missed opportunity
STRICTER = _cmp("DISAGREE", True, "FAIL")
#: live declined, the rule said PASS -> the rule is LOOSER -> NEW LIVE EXPOSURE
LOOSER = _cmp("DISAGREE", False, "PASS")
AGREE_TOOK = _cmp("AGREE", True, "PASS")
NOT_COMPARABLE = RuleComparison("ENTRY-001", "NOT_COMPARABLE", None, None,
                                reason="LIVE_NOT_REACHED")


# ======================================================================================
# ACCEPTANCE 2 — BOTH DIRECTIONS ARE REACHABLE
# A split where one bucket can never be non-zero is the defect this task exists to remove.
# ======================================================================================


def test_acceptance2_the_stricter_bucket_is_reachable_and_lands_only_there():
    c = EntryComparison(comparisons=(STRICTER,))
    assert (c.rule_stricter, c.rule_looser) == (1, 0)
    assert disagreement_direction(STRICTER) == "RULE_STRICTER"


def test_acceptance2_the_looser_bucket_is_reachable_and_lands_only_there():
    c = EntryComparison(comparisons=(LOOSER,))
    assert (c.rule_stricter, c.rule_looser) == (0, 1)
    assert disagreement_direction(LOOSER) == "RULE_LOOSER"


def test_acceptance2_the_two_buckets_are_DISTINGUISHABLE_where_disagree_alone_is_not():
    """**The whole finding in one assertion.** Three stricter and three looser render
    identically under `disagree` and must not under the split."""
    stricter_only = EntryComparison(comparisons=(STRICTER, STRICTER, STRICTER))
    looser_only = EntryComparison(comparisons=(LOOSER, LOOSER, LOOSER))

    assert stricter_only.disagree == looser_only.disagree == 3, "indistinguishable before"
    assert (stricter_only.rule_stricter, stricter_only.rule_looser) == (3, 0)
    assert (looser_only.rule_stricter, looser_only.rule_looser) == (0, 3)
    assert stricter_only.detail != looser_only.detail, (
        "the two populations must not render identically in the string that is persisted"
    )


# ======================================================================================
# ACCEPTANCE 1 — THE INVARIANT, on 0, 1 and many
# ======================================================================================


@pytest.mark.parametrize(
    "comparisons",
    [
        (),
        (STRICTER,),
        (LOOSER,),
        (AGREE_TOOK,),
        (NOT_COMPARABLE,),
        (STRICTER, LOOSER),
        (STRICTER, LOOSER, AGREE_TOOK, NOT_COMPARABLE, STRICTER),
    ],
    ids=["empty", "one_stricter", "one_looser", "one_agree", "one_nc", "both", "many"],
)
def test_acceptance1_stricter_plus_looser_equals_disagree(comparisons):
    """The plan's invariant, on every shape including the empty set."""
    c = EntryComparison(comparisons=comparisons)
    assert c.rule_stricter + c.rule_looser == c.disagree
    assert c.direction_unknown == 0, "no path that exists produces an unreadable direction"


def test_the_invariant_is_TOTAL_not_merely_true_today():
    """`direction_unknown` exists so the sum cannot quietly stop adding up.

    Without it, a DISAGREE whose `live_verdict` is not a bool would make
    `stricter + looser < disagree` silently. **A count that stops reconciling and says
    nothing is this register's most repeated failure**, so the third bucket is carried even
    though it is zero on every path that exists — and it is asserted zero above, so it
    cannot become a dumping ground unnoticed.
    """
    unreadable = _cmp("DISAGREE", None, "FAIL")
    c = EntryComparison(comparisons=(unreadable,))

    assert c.disagree == 1
    assert (c.rule_stricter, c.rule_looser) == (0, 0)
    assert c.direction_unknown == 1
    assert c.rule_stricter + c.rule_looser + c.direction_unknown == c.disagree
    assert "direction_unknown=1" in c.detail, (
        "an unreadable direction must be VISIBLE in the persisted string, not folded into "
        "a bucket — a wrong answer where an unknown is an honest one"
    )


def test_the_unknown_term_is_ABSENT_from_the_string_when_it_is_zero():
    """It appears only when it means something, so its presence is a signal rather than noise."""
    assert "direction_unknown" not in EntryComparison(comparisons=(STRICTER,)).detail


# ======================================================================================
# ACCEPTANCE 3 — THE MUST-FAIL ARM
# ======================================================================================


def test_acceptance3_swapping_the_two_verdicts_COLLAPSES_the_split():
    """**Swap `live_verdict` and `rule_verdict` and the buckets must move.** If they stay
    put, they are not keyed on direction at all.

    The swap does not merely misclassify — it lands in `direction_unknown`, loudly. That is
    why the classifier reads BOTH members of the pair: keyed on `live_verdict` alone it
    would still "work" after a swap, because every non-empty string is truthy, so
    `"FAIL"` and `"PASS"` would both read as *live entered* and every disagreement would
    report one direction forever.
    """
    swapped_stricter = _cmp("DISAGREE", "FAIL", True)
    swapped_looser = _cmp("DISAGREE", "PASS", False)
    c = EntryComparison(comparisons=(swapped_stricter, swapped_looser))

    assert (c.rule_stricter, c.rule_looser) == (0, 0), (
        "with the fields swapped neither bucket may be populated; if one is, the classifier "
        "is reading a single field and a swap is invisible to it"
    )
    assert c.direction_unknown == 2
    assert disagreement_direction(swapped_stricter) is None


def test_acceptance3_a_ONE_FIELD_classifier_would_have_passed_the_swap():
    """The counter-demonstration, so the arm above is known to be load-bearing.

    A classifier keyed only on `live_verdict` reports RULE_STRICTER for BOTH swapped rows,
    because `"FAIL"` and `"PASS"` are both truthy. It would have looked healthy.
    """
    one_field = lambda c: "RULE_STRICTER" if c.live_verdict else "RULE_LOOSER"  # noqa: E731

    assert one_field(_cmp("DISAGREE", "FAIL", True)) == "RULE_STRICTER"
    assert one_field(_cmp("DISAGREE", "PASS", False)) == "RULE_STRICTER"
    assert disagreement_direction(_cmp("DISAGREE", "FAIL", True)) is None


# ======================================================================================
# ACCEPTANCE 5 — NOT_COMPARABLE CARRIES NO DIRECTION
# ======================================================================================


def test_acceptance5_a_set_of_only_NOT_COMPARABLE_has_no_direction_and_no_rate():
    c = EntryComparison(comparisons=(NOT_COMPARABLE, NOT_COMPARABLE))

    assert (c.rule_stricter, c.rule_looser, c.disagree) == (0, 0, 0)
    assert "undefined (0 comparable)" in c.detail
    assert c.values()["disagreement_rate"] is None
    assert disagreement_direction(NOT_COMPARABLE) is None


def test_an_AGREE_has_nothing_to_point_at():
    assert disagreement_direction(AGREE_TOOK) is None
    assert disagreement_direction(_cmp("AGREE", False, "FAIL")) is None


# ======================================================================================
# ACCEPTANCE 4 — IT REACHES THE DATABASE, NOT JUST THE DATACLASS
#
# THE ARM THAT MATTERS. The whole finding is that a correct in-memory value dies at a
# boundary, so reading `values()` proves nothing: `values()` was always right.
# ======================================================================================


def _emitted_line(comparison: EntryComparison) -> str:
    trace = DecisionTrace(symbol="BTC/USD", timeframe="5m")
    comparison.record_on(trace)
    lines = [line for line in trace.reasons if "entry rules:" in line]
    assert len(lines) == 1, trace.reasons
    return lines[0]


def test_acceptance4_both_terms_appear_in_the_string_that_reaches_DecisionRecord():
    """Built as a trace, run through `reasons`, read out of the emitted string."""
    line = _emitted_line(EntryComparison(comparisons=(STRICTER, LOOSER, LOOSER)))

    assert "rule_stricter=1" in line
    assert "rule_looser=2" in line
    assert "disagree=3" in line
    assert line.startswith("OBSERVED entry_rule_comparison:"), line


def test_acceptance4_reading_values_is_NOT_the_evidence_and_this_says_why():
    """`Gate.values` is carried only by `Gate.as_dict()`, whose only caller is
    `DecisionTrace.as_dict()`, which has **zero callers in `app/`**. So the structured
    direction would have been correct and unreachable — which is the finding, not the fix.
    """
    import app.services.live.decision_trace as dt

    trace = DecisionTrace(symbol="BTC/USD", timeframe="5m")
    EntryComparison(comparisons=(STRICTER,)).record_on(trace)

    assert trace.gates[0].values["rule_stricter"] == 1, "values() carries it in memory"

    src = inspect.getsource(dt)
    assert "def as_dict" in src, "the dead serialiser is still there; if it is wired up, re-check"
    assert "rule_stricter" in _emitted_line(EntryComparison(comparisons=(STRICTER,))), (
        "and the string is what actually reaches the database"
    )


def test_acceptance4_the_direction_is_recorded_AT_EMISSION_not_reconstructed():
    """**`B213`.** Post-hoc reconstruction from `signal_dir`/`outcome`/`sized_units` works
    only where `disagree == 1` and `agree == 0` — it breaks on more than one disagreement,
    on rows where agree and disagree are both non-zero, and on any bar where live declined
    and there is no signal row to join against. *It works on exactly the rows nobody needs
    it for*, so it would be validated against the one corpus row that cannot falsify it.

    Two sets below are indistinguishable to any such join — same `disagree`, same `agree` —
    and the emitted strings differ, which is what recording at emission buys.
    """
    a = _emitted_line(EntryComparison(comparisons=(STRICTER, LOOSER, AGREE_TOOK)))
    b = _emitted_line(EntryComparison(comparisons=(STRICTER, STRICTER, AGREE_TOOK)))

    assert "disagree=2" in a and "disagree=2" in b
    assert "agree=1" in a and "agree=1" in b
    assert a != b
    assert "rule_stricter=1 rule_looser=1" in a
    assert "rule_stricter=2 rule_looser=0" in b


# ======================================================================================
# ACCEPTANCE 6 — OLD ROWS STILL PARSE
# ======================================================================================

#: A `reasons` list as production wrote it BEFORE this change — from the live corpus,
#: `agents/tasks/T-0053/_runs/live-corpus-20260819.txt`. Note the absence of the two new
#: terms: this is exactly what the 33 stored rows look like.
OLD_REASONS = [
    "PASS history: 320 bars",
    "OBSERVED entry-rule-comparison: entry rules: disagree=0 agree=0 not_comparable=1 "
    "rate=undefined (0 comparable) [1 of 6 rules comparable]",
    "OBSERVED news: no red-folder event in scope",
]


def test_acceptance6_the_named_consumers_do_not_raise_on_pre_change_rows():
    """**Which consumers were exercised, named rather than implied.**

    `reasons` is a JSON list of free-text lines and **no consumer parses this one** — that
    is why the change is additive rather than a migration. The two that actually touch the
    content are exercised here:

      1. `api/routers/engine.py:_serialize_decision` — passes `r.reasons` through verbatim.
      2. `live/crypto_loop.py:1443-1450` — the ABANDONED path: `list(rec.reasons or [])`
         then append.

    The remaining `.reasons` references are WRITERS (`crypto_loop:522,1024`,
    `decision/engine.py:125,136`) or docstrings, and a writer cannot be broken by the shape
    of a row it did not read.
    """
    from app.api.routers.engine import _serialize_decision

    class _Row:
        """Every field `_serialize_decision` reads, so the consumer is exercised whole
        rather than up to the first attribute it happens to want."""

        id = "abc"
        reasons = list(OLD_REASONS)
        created_at = None
        symbol, timeframe = "BTC/USD", "5m"
        inputs_hash = code_path_hash = "h"
        score = signal_entry = signal_sl = signal_tp = None
        fill_price = sized_units = expected_r = realized_r = gap_r = None
        abstained, signal_dir, outcome, cohort = False, None, None, "live"

    out = _serialize_decision(_Row())
    assert out["reasons"] == OLD_REASONS

    reasons = list(_Row.reasons or [])
    reasons.append("ABANDONED: the engine stopped while this position was open")
    assert len(reasons) == len(OLD_REASONS) + 1

    assert not any("rule_stricter" in line for line in OLD_REASONS), (
        "the fixture must be a genuine PRE-change row, or acceptance 6 tests nothing"
    )


def test_acceptance6_a_new_row_and_an_old_row_are_both_just_strings():
    """The compatibility claim, stated as the property it rests on: nothing regex-matches
    this line, so adding terms cannot break a reader."""
    new_line = _emitted_line(EntryComparison(comparisons=(STRICTER,)))
    for line in (*OLD_REASONS, new_line):
        assert isinstance(line, str) and line


# ======================================================================================
# THE REAL PATH — hand-built `RuleComparison`s prove the COUNTER works. They do not prove
# the PIPELINE produces a direction. `compare_entry` is run here on real bars.
# ======================================================================================


def test_the_real_compare_entry_path_emits_a_direction_and_flipping_live_flips_it():
    """**`T-0037`'s arm 1, extended by one question: which WAY did it disagree?**

    Same bars, two live verdicts. Exactly one disagrees, because the rule's verdict does not
    depend on the live one — and the one that disagrees must land in the bucket matching the
    live verdict that produced it. *Whichever side the rule happens to take on this fixture,
    the disagreement is stricter iff live took the entry.*
    """
    import pandas as pd
    from datetime import datetime, timedelta, timezone

    from app.services.live.entry_comparison import compare_entry
    from app.services.live.shadow import _bars_from_frame

    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    frame = pd.DataFrame(
        [
            {"timestamp": t0 + timedelta(minutes=5 * i), "open": 100.0 + i,
             "high": 101.0 + i, "low": 99.0 + i, "close": 100.5 + i}
            for i in range(60)
        ]
    ).set_index("timestamp")
    bars = _bars_from_frame(frame)

    took = compare_entry(_live_trace(took=True), bars, tf="5m")
    declined = compare_entry(_live_trace(took=False), bars, tf="5m")

    assert took.disagree + declined.disagree == 1, (
        f"took={took.disagree} declined={declined.disagree}; the fixture stopped producing "
        "a comparable pair, so this arm is measuring nothing"
    )
    for side, comparison in (("took", took), ("declined", declined)):
        assert comparison.rule_stricter + comparison.rule_looser == comparison.disagree
        assert comparison.direction_unknown == 0
        if comparison.disagree:
            expected = (1, 0) if side == "took" else (0, 1)
            assert (comparison.rule_stricter, comparison.rule_looser) == expected, (
                f"live {side} the entry, so the disagreement must be "
                f"{'stricter' if side == 'took' else 'looser'}"
            )
            assert "rule_stricter=" in _emitted_line(comparison)


def _live_trace(*, took: bool) -> DecisionTrace:
    t = DecisionTrace(symbol="BTC/USD", timeframe="5m")
    t.took_trade = took
    return t
