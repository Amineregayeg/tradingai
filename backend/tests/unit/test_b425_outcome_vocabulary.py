"""B425 — the analysis layer knew SIX outcomes while the database held EIGHT, and the two it did
not know were answered with a guess.

**THE DEFECT IS AN EMPTINESS AXIS, not a missing token set**, and that reframing is what decides the
fix. Three states reached two paths:

```
outcome IS NULL        no token was ever written      -> infer from the sign of realized_r
outcome = "WIN"        a token this layer knows       -> use it
outcome = "REJECTED"   a token this layer does NOT    -> WAS TREATED AS THE FIRST
```

The fallback is **correct** for the first. It is not a fallback for the third, because the third
row *did* say what happened — the sign of R is what you consult when the record never said. So the
fix keeps the fallback and makes it unreachable from a present token; an entry reading "classify
from the constants and refuse" would have invited deleting it.

It is `_position_units`' absent-vs-present-`None` one layer up: there `.get()` collapsed the two,
here *"no set matched"* did. Same family, same function, one layer apart.

**REFUSING RETURNS A VALUE, IT DOES NOT RAISE.** `_classify_outcome` runs once per row over the
whole corpus, so a raise would end an entire evaluation run because of one row — the `M-5` shape,
where a bookkeeping failure killed its caller. Refuse means *do not guess*: exclude the row, count
it, and surface the count. **A count nobody can see is the same defect wearing a different hat.**
"""
from __future__ import annotations

import pytest

from app.models.decision_record import (
    DECISION_OUTCOMES,
    OUTCOME_ABANDONED,
    OUTCOME_ABSTAINED,
    OUTCOME_BREAKEVEN,
    OUTCOME_LOSS,
    OUTCOME_OPEN,
    OUTCOME_REJECTED,
    OUTCOME_SUBMITTING,
    OUTCOME_UNSIZED_FILL,
    OUTCOME_WIN,
)
from app.services.evaluation.feedback import (
    BUCKET_UNRECOGNISED,
    _NOT_CLOSED,
    _OUTCOME_BUCKETS,
    _classify_outcome,
    analyze,
)


def _row(outcome, realized_r=2.0):
    """A row complete enough to be CLOSED evidence if its outcome lets it be.

    Deliberately a winner on every numeric axis: +2R realized against a +3R target. If a
    classification leaks into the evidence set, it leaks as a win, which is the loudest
    possible way for these arms to fail.
    """
    rec = {
        "signal_dir": "LONG", "signal_entry": 100.0, "signal_sl": 99.0, "signal_tp": 103.0,
        "expected_r": 3.0, "realized_r": realized_r, "gap_r": (realized_r or 0.0) - 3.0,
        "fill_price": 100.0, "cohort": "paper", "abstained": False,
    }
    if outcome is not _ABSENT:
        rec["outcome"] = outcome
    return rec


_ABSENT = object()


# =====================================================================================
# THE VOCABULARY CANNOT DRIFT AGAIN
# =====================================================================================

def test_the_buckets_cover_the_DATABASE_vocabulary_EXACTLY():
    """**THE ARM THAT MAKES B425 UNREPEATABLE**, and it compares SETS.

    `B416`: a length check passes on a right-sized wrong membership. Both directions are
    separate failures with separate messages, because they are different mistakes — a
    missing key is a value the analysis will refuse, an extra key is a value the database
    cannot hold and therefore a second encoding forming again.
    """
    missing = set(DECISION_OUTCOMES) - set(_OUTCOME_BUCKETS)
    extra = set(_OUTCOME_BUCKETS) - set(DECISION_OUTCOMES)

    assert not missing, (
        f"the database can hold {sorted(missing)} and this layer has no bucket for them, so every "
        f"such row will be refused. That is B425 exactly: the CHECK grew and the reader did not."
    )
    assert not extra, (
        f"{sorted(extra)} are classified here but cannot be stored, so they are a parallel "
        f"vocabulary forming again — the thing this entry deleted."
    )


def test_the_TWO_THAT_DRIFTED_are_named_rather_than_merely_counted():
    """**A count is not a denominator; the identity of what was counted is** (`B424` residual 3).

    The arm above is satisfied by any two sets that happen to match. These are the two values
    that were actually missing, so they are asserted by name: if the model's constants and this
    mapping were ever regenerated from each other, the arm above would go on passing while
    covering nothing anyone chose.
    """
    assert _OUTCOME_BUCKETS[OUTCOME_REJECTED] == "rejected"
    assert _OUTCOME_BUCKETS[OUTCOME_UNSIZED_FILL] == "unsized_fill"
    # 8 -> 9 with `SUBMITTING` (`T-0144`, migration `0017`), which has its own arm below.
    assert len(DECISION_OUTCOMES) == 9, (
        f"the database vocabulary changed size to {len(DECISION_OUTCOMES)} — that is not a "
        f"failure, but the two values this entry was written about are no longer the whole story"
    )


def test_the_refusal_marker_cannot_be_confused_with_a_real_bucket():
    """`BUCKET_UNRECOGNISED` is excluded by value. If it ever equalled a real bucket it would be
    silently promoted into the evidence — the refusal becoming an answer."""
    assert BUCKET_UNRECOGNISED not in set(_OUTCOME_BUCKETS.values())


# =====================================================================================
# THE AXIS — ABSENT IS NOT THE SAME QUESTION AS UNRECOGNISED
# =====================================================================================

def test_ABSENT_and_PRESENT_BUT_UNRECOGNISED_are_DIFFERENT_answers():
    """**THE HEART OF THE ENTRY.** Same record, same `realized_r`, one carries no outcome and one
    carries a token this layer does not know. Before the fix both returned `"win"`."""
    absent = _classify_outcome(_row(_ABSENT, 2.0), 2.0)
    unknown = _classify_outcome(_row("NOT_A_REAL_OUTCOME", 2.0), 2.0)

    assert absent == "win", "the no-token fallback was removed — it is correct for NULL rows"
    assert unknown == BUCKET_UNRECOGNISED
    assert absent != unknown, (
        "a row that never said and a row that said something unreadable got the same answer, "
        "which is the collapse this entry is about"
    )


@pytest.mark.parametrize("realized_r", [2.0, -2.0, 0.0, None])
def test_an_unrecognised_token_is_INDEPENDENT_of_the_sign_of_R(realized_r):
    """**The strong form of "does not guess".** Not merely *is it refused* — the refusal must not
    VARY with the number it was previously inferred from. If any R value changes the answer, the
    inference is still reachable from a present token by some path."""
    assert _classify_outcome(_row("NOT_A_REAL_OUTCOME", realized_r), realized_r) == BUCKET_UNRECOGNISED


@pytest.mark.parametrize("token,expected", [
    (OUTCOME_WIN, "win"), (OUTCOME_LOSS, "loss"), (OUTCOME_BREAKEVEN, "be"),
    (OUTCOME_OPEN, "open"), (OUTCOME_ABSTAINED, "abstained"), (OUTCOME_ABANDONED, "abandoned"),
    (OUTCOME_REJECTED, "rejected"), (OUTCOME_UNSIZED_FILL, "unsized_fill"),
    (OUTCOME_SUBMITTING, "submitting"),
])
def test_every_STORABLE_outcome_classifies_as_itself_regardless_of_R(token, expected):
    """Driven with `realized_r = +2.0`, which is the value the old fallback would have turned into
    a `"win"`. Six of these passed before the fix; two did not, and those two are the entry."""
    assert _classify_outcome(_row(token, 2.0), 2.0) == expected


def test_an_EMPTY_STRING_is_absence_and_not_a_refusal():
    """**A declared ruling, recorded so it is not silently reverted.**

    `""` means *nothing was written*, not *something unreadable*, so it takes the no-token path.
    This is a deliberate behaviour change from the old `_OPEN_TOKENS = {"open", ""}`, which
    answered `"open"` for an empty string even on a row carrying +2R — and it is unreachable
    either way: the CHECK admits `NULL` or one of the nine, and NULL serialises to `None`.
    """
    assert _classify_outcome(_row("", 2.0), 2.0) == "win"
    assert _classify_outcome(_row("   ", 2.0), 2.0) == "win", "whitespace is not a token either"
    assert _classify_outcome(_row("", None), None) == "open", "with no R it is open, as before"


# =====================================================================================
# REFUSING MUST NOT RAISE, AND MUST NOT VANISH
# =====================================================================================

def test_one_unreadable_row_does_NOT_take_down_the_whole_RUN():
    """**Review's caution, made an arm.** `_classify_outcome` runs once per row; raising on an
    unknown token would end an evaluation over 2000 rows because of one of them (`M-5`)."""
    corpus = [_row(OUTCOME_WIN, 3.0) for _ in range(40)]
    corpus += [_row(OUTCOME_LOSS, -1.0) for _ in range(40)]
    corpus.insert(37, _row("SOMETHING_NOBODY_HAS_SEEN", 2.0))

    result = analyze(corpus, {"risk_pct": 0.01}, min_evidence=30)

    assert result["n"] == 80, f"the good rows did not survive the bad one: n={result['n']}"
    assert result["excluded"]["unrecognised"] == 1


def test_the_refusal_is_COUNTED_and_the_count_is_RETURNED():
    """A refusal nobody can count is indistinguishable from no refusal. This is the half that
    stops the fix from becoming the defect it replaced: `REJECTED` was invisible for two
    migrations precisely because the corpus silently shrank."""
    corpus = [_row(OUTCOME_WIN, 3.0) for _ in range(31)]
    corpus += [_row(OUTCOME_REJECTED, 2.0) for _ in range(4)]
    corpus += [_row(OUTCOME_UNSIZED_FILL, 2.0) for _ in range(3)]
    corpus += [_row("SCRATCH", 2.0) for _ in range(2)]

    result = analyze(corpus, {"risk_pct": 0.01}, min_evidence=30)

    assert result["n"] == 31, "an excluded row reached the evidence set"
    assert result["excluded"] == {"rejected": 4, "unsized_fill": 3, "unrecognised": 2}


def test_the_counts_are_on_BOTH_return_paths_including_the_ABSTAIN_one():
    """**The abstain path is where an unread vocabulary actually bites.** The evidence is thin
    BECAUSE rows were refused, so that is the branch that most needs to say so — and it is the
    branch a payload key added to the happy path alone would miss."""
    corpus = [_row(OUTCOME_WIN, 3.0) for _ in range(4)]
    corpus += [_row("SOMETHING_NOBODY_HAS_SEEN", 2.0) for _ in range(60)]

    result = analyze(corpus, {"risk_pct": 0.01}, min_evidence=30)

    assert result["abstained"] is True
    assert result["excluded"]["unrecognised"] == 60
    assert "unrecognised=60" in result["abstain_reason"], (
        f"the reason says the evidence is thin without saying what it was spent on: "
        f"{result['abstain_reason']!r}"
    )


def test_a_SUBMITTING_row_is_EXCLUDED_under_its_OWN_name_and_never_becomes_evidence():
    """**`KILL_SET.md` M-5 (feedback). `SUBMITTING` is the engine's pre-send record (`T-0144` R11').**

    It says an order was about to be sent and nothing about what the venue did (`B423`), so it carries no
    realized information. Its bucket must be in `_NOT_CLOSED`: without that, a row with a bucket of its
    own and a `realized_r` on it becomes CLOSED evidence — driven here with +2R, the loudest leak. And it
    is counted as `submitting`, not `unrecognised`: a stranded pre-send row is a known state, and folding
    it into the refusal count would make a vocabulary gap and a crash residue read the same.
    """
    corpus = [_row(OUTCOME_WIN, 3.0) for _ in range(31)]
    corpus += [_row(OUTCOME_SUBMITTING, 2.0) for _ in range(5)]

    result = analyze(corpus, {"risk_pct": 0.01}, min_evidence=30)

    assert result["n"] == 31, f"a SUBMITTING row reached the evidence set: n={result['n']}"
    assert result["excluded"] == {"submitting": 5}, result["excluded"]
    assert "submitting" in _NOT_CLOSED


def test_a_REJECTED_row_is_not_counted_as_a_WIN():
    """The live effect, stated at the severity it actually has. Production holds zero `REJECTED`
    rows today, so this is a regression guard rather than a repair — **quiet is not inert.**"""
    corpus = [_row(OUTCOME_REJECTED, 2.0) for _ in range(50)]
    result = analyze(corpus, {"risk_pct": 0.01}, min_evidence=1)

    assert result["n"] == 0, "a refused order was counted as realized evidence"
    assert result["excluded"]["rejected"] == 50


def test_SCRATCH_is_refused_rather_than_FOLDED_INTO_BREAKEVEN():
    """**The manager's caution, and it is `B423`'s lesson.** The backtest engine
    (`app/services/backtest/engine.py:521`) emits `win|loss|scratch|open`; the deleted token sets
    mapped `scratch` onto breakeven. Nothing feeds that engine's trades to `analyze()` — the join
    was never made — so the mapping was never exercised, and re-asserting it would claim the two
    vocabularies mean the same thing without anyone having measured that. `scratch` has no
    counterpart among the eight, so it cannot be a rename. It is refused and counted (`B426`).
    """
    assert _classify_outcome({"outcome": "scratch"}, 0.0) == BUCKET_UNRECOGNISED
    assert _classify_outcome({"outcome": "scratch"}, 0.0) != "be"


@pytest.mark.parametrize("alias", ["lose", "breakeven", "break_even", "scratch", "abstain"])
def test_the_DELETED_ALIASES_are_refused_not_silently_accepted(alias):
    """The deletion, driven. Each of these used to classify; none can be stored by the CHECK, and
    nothing produces them. They now surface in the counts rather than resolving to a bucket."""
    assert _classify_outcome({"outcome": alias}, 1.0) == BUCKET_UNRECOGNISED


def test_lowercase_spellings_of_a_REAL_outcome_still_classify():
    """Case-insensitivity was a property of the old sets and is kept deliberately: the serializer
    passes the column through verbatim, but `analyze()` is documented as a pure function over
    dicts and a caller hand-building one should not be caught out by case."""
    assert _classify_outcome({"outcome": "win"}, None) == "win"
    assert _classify_outcome({"outcome": " Unsized_Fill "}, None) == "unsized_fill"
