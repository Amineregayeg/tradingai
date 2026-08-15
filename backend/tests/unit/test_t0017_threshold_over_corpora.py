"""T-0017 — a declared threshold validated over a SET of corpora, not the one it was declared on.

WHICH ASSERTIONS READ THE FIXTURE AND WHICH READ LIVE DATA, because they mean different
things when they go red:

    EVERY assertion in this file reads `tests/fixtures/btcusdtp_5m_1500.csv`.
    NOTHING here fetches. A red run is therefore UNAMBIGUOUSLY A DEFECT — the market
    cannot move under a pinned fixture, so nothing excuses a failure.

A live check would be useful for detecting regime change and could not be this test: the
corpora on which a marginal `k` passes are the OLDEST windows in a fetch, and a live fetch
anchors to now. Within about six hours the marginal case is gone, the mutation below has no
target, and a vacuous mutation passes. Trimming from the END is harmless — only forward
motion destroys it, which is the direction real time runs and the direction every CI run
experiences.

THE FIXTURE WAS PINNED BEFORE ANY `k` WAS CHOSEN, AND THE PLAN'S PREDICTED `k` WAS WRONG.
The plan's live measurement found `k = 3.5` marginal at 6 of 54. In the fixture actually
captured, `3.5` is REJECTED on all 54 and `k = 2.5` is the marginal one at 26 of 54. The
mutation therefore runs on 2.5. **The fixture was not recaptured to look for a friendlier
number** — fixture-shopping is selecting data to make a test pass, and the property under
test is that the set form is STRICTER than the single-corpus form, not that any particular
`k` is marginal.

THE CORPUS SET IS STILL ONE REGIME. 54 sliding windows over five days of one symbol is
fifty-four views of the same market, not fifty-four markets. Its value is reproducibility,
not currency, and it will age: a fixture nobody re-captures describes a market that no
longer exists. That is acceptable and it is stated rather than assumed.
"""
from __future__ import annotations

import csv
import dataclasses
from datetime import datetime
from pathlib import Path

import pytest

from app.services.rules.consolidation import (
    ACCEPTED, DECLARED_THRESHOLD, MARGINAL, REJECTED, validate_over_corpora,
)
from app.services.rules.prim_001_swings import Bar

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "btcusdtp_5m_1500.csv"

#: 863-bar corpora one hour apart at 5m — the corpus length the threshold was declared
#: against, so the set form is comparing like with like.
CORPUS_BARS = 863
STEP_BARS = 12
EXPECTED_CORPORA = 54

#: Measured on the pinned fixture, 2026-08-15. Recorded so a change in these is visible as
#: a change rather than as a differently-worded pass.
MEASURED = {
    2.0: (0, "rejected everywhere"),
    2.5: (26, "MARGINAL — the mutation target"),
    3.0: (54, "accepted everywhere — the declared value"),
    3.5: (0, "rejected everywhere in THIS fixture, unlike the plan's live measurement"),
    4.0: (0, "rejected everywhere"),
    5.0: (0, "rejected everywhere"),
}


def _bars() -> list[Bar]:
    out: list[Bar] = []
    with FIXTURE.open() as fh:
        for row in csv.DictReader(fh):
            out.append(Bar(
                time=datetime.fromisoformat(row["time"]),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
            ))
    return out


def _validate(k: float):
    return validate_over_corpora(
        _bars(), tf="5m",
        threshold=dataclasses.replace(DECLARED_THRESHOLD, k=k),
        corpus_bars=CORPUS_BARS, step_bars=STEP_BARS,
    )


# ---------------------------------------------------------------------------
# Criteria 1 and 6 — a fraction, with its denominator
# ---------------------------------------------------------------------------
def test_the_declared_threshold_is_in_bounds_on_every_corpus():
    """CRITERION 1. `54/54` and `6/54` must not produce the same answer.

    The declared `k = 3.0` is the strong case: in bounds on every corpus in the set, which
    is a property the single-corpus predicate cannot express at all.
    """
    result = _validate(3.0)
    assert result.total == EXPECTED_CORPORA, (
        f"expected {EXPECTED_CORPORA} corpora, built {result.total} — the fixture or the "
        "windowing changed, and every number in this file is against the old set"
    )
    assert result.in_bounds == result.total
    assert result.verdict == ACCEPTED
    assert 5.0 <= result.min_rate_pct and result.max_rate_pct <= 35.0


def test_the_result_carries_its_own_denominator():
    """CRITERION 6. A check over one corpus and a check over fifty are identically green.

    So the count is a FIELD on the result rather than a log line, and every consumer gets
    it whether or not they thought to ask.
    """
    result = _validate(3.0)
    assert result.total == EXPECTED_CORPORA
    assert result.corpus_bars == CORPUS_BARS
    assert f"of {EXPECTED_CORPORA} corpora" in result.summary
    assert f"{CORPUS_BARS} bars each" in result.summary


def test_an_empty_corpus_set_is_not_an_acceptance():
    """Zero corpora examined is not a pass. Validating nothing validates nothing."""
    result = validate_over_corpora(
        _bars()[:10], tf="5m", threshold=DECLARED_THRESHOLD, corpus_bars=CORPUS_BARS,
    )
    assert result.total == 0
    assert result.verdict == REJECTED
    assert result.verdict != ACCEPTED


# ---------------------------------------------------------------------------
# Criterion 3 — three outcomes, because two destroy the interesting one
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("k,expected", [
    (2.0, REJECTED), (2.5, MARGINAL), (3.0, ACCEPTED),
    (3.5, REJECTED), (4.0, REJECTED), (5.0, REJECTED),
])
def test_each_k_gets_its_measured_verdict(k, expected):
    result = _validate(k)
    assert result.verdict == expected, result.summary
    assert result.in_bounds == MEASURED[k][0], (
        f"{result.summary}\nexpected {MEASURED[k][0]}/{EXPECTED_CORPORA} "
        f"({MEASURED[k][1]})"
    )


def test_marginal_is_neither_pass_nor_fail():
    """CRITERION 3. Collapsing MARGINAL into PASS hides a value that will start failing;
    collapsing it into FAIL hides that it nearly works. Both are information."""
    marginal = _validate(2.5)
    assert marginal.verdict == MARGINAL
    assert marginal.verdict not in (ACCEPTED, REJECTED)
    assert 0 < marginal.in_bounds < marginal.total


# ---------------------------------------------------------------------------
# Criterion 4 — THE MUTATION, against the pinned fixture
# ---------------------------------------------------------------------------
def test_the_set_form_rejects_a_value_the_single_corpus_form_accepts():
    """THE CRITERION. The set form must be STRICTER than the single-corpus form.

    `k = 2.5` is in bounds on 26 of the 54 corpora and outside on the other 28. So a
    declaration anchored on any one of those 26 passes `rate_is_within_bounds()` — the same
    predicate, on the same kind of evidence, that accepts the correct value — while the set
    form reports MARGINAL and refuses to call it accepted.

    That is the whole gap: one number cannot distinguish "inside the band" from "inside the
    band on the window I happened to measure."
    """
    bars = _bars()
    k = 2.5
    threshold = dataclasses.replace(DECLARED_THRESHOLD, k=k)

    # Every corpus, measured individually, exactly as a declaration would have done.
    from app.services.rules.consolidation import detection_rate_pct
    per_corpus = [
        detection_rate_pct(bars[s:s + CORPUS_BARS], tf="5m", threshold=threshold)[0]
        for s in range(0, len(bars) - CORPUS_BARS + 1, STEP_BARS)
    ]
    accepting = [
        r for r in per_corpus
        if threshold.rate_floor_pct <= r <= threshold.rate_ceiling_pct
    ]
    assert accepting, (
        "no corpus in the fixture accepts k=2.5, so the single-corpus form would reject it "
        "too and this mutation has no target — see the module docstring on why the fixture "
        "must NOT be recaptured to find one"
    )

    # THE SINGLE-CORPUS FORM ACCEPTS IT.
    declared_on_a_lucky_window = dataclasses.replace(
        threshold, measured_rate_pct=accepting[0]
    )
    assert declared_on_a_lucky_window.rate_is_within_bounds(), (
        "the single-corpus predicate must accept this value — if it does not, the mutation "
        "is not demonstrating that the set form is stricter"
    )

    # THE SET FORM DOES NOT.
    result = validate_over_corpora(
        bars, tf="5m", threshold=threshold,
        corpus_bars=CORPUS_BARS, step_bars=STEP_BARS,
    )
    assert result.verdict != ACCEPTED, (
        f"the set form accepted a value the single-corpus form accepts only on "
        f"{len(accepting)} of {len(per_corpus)} windows: {result.summary}"
    )
    assert result.verdict == MARGINAL
    assert result.in_bounds == len(accepting)


def test_the_declared_value_survives_the_stricter_form():
    """The other half, and it is not decoration: a stricter check that rejects the declared
    value as well would be useless. `k = 3.0` is accepted on all 54, so the mutation above
    demonstrates strictness rather than a check that refuses everything."""
    assert _validate(3.0).verdict == ACCEPTED
    assert _validate(2.5).verdict == MARGINAL


# ---------------------------------------------------------------------------
# Criterion 5 — the floor is load-bearing, measured rather than argued
# ---------------------------------------------------------------------------
def test_a_ceiling_alone_accepts_a_detector_that_never_fires():
    """CRITERION 5. The floor was added on argument; this is the measurement that earns it.

    `k = 2.0` detects consolidation on ~0.1% of windows — a detector that never fires,
    which refuses every reversal instead of permitting every one. Against a CEILING ALONE
    it is in bounds on every corpus, and the low end is the more dangerous one to review
    because "not permissive" reads as conservative.
    """
    ceiling_only = dataclasses.replace(DECLARED_THRESHOLD, k=2.0, rate_floor_pct=0.0)
    without_floor = validate_over_corpora(
        _bars(), tf="5m", threshold=ceiling_only,
        corpus_bars=CORPUS_BARS, step_bars=STEP_BARS,
    )
    assert without_floor.verdict == ACCEPTED, (
        "a ceiling alone must accept a detector that never fires — if it does not, this "
        "test is no longer demonstrating why the floor exists"
    )
    assert without_floor.max_rate_pct < 1.0, "k=2.0 should barely fire at all"

    # WITH the floor, rejected on every one of them.
    with_floor = _validate(2.0)
    assert with_floor.verdict == REJECTED
    assert with_floor.in_bounds == 0


def test_the_ceiling_is_load_bearing_too():
    """The mirror. `k = 5.0` fires on ~86% of windows — a detector that permits everything
    — and a floor alone accepts it."""
    floor_only = dataclasses.replace(DECLARED_THRESHOLD, k=5.0, rate_ceiling_pct=100.0)
    without_ceiling = validate_over_corpora(
        _bars(), tf="5m", threshold=floor_only,
        corpus_bars=CORPUS_BARS, step_bars=STEP_BARS,
    )
    assert without_ceiling.verdict == ACCEPTED
    assert without_ceiling.min_rate_pct > 50.0
    assert _validate(5.0).verdict == REJECTED
