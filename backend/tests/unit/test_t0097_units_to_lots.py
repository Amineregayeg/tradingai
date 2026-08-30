"""T-0097 — the units-to-lots contract arm. **This one is on the WRITE path.**

`T-0078` established this as the one category-3 contract arm that does not exist, and row 5's
argument applies with more force here: the others guard what a record SAYS; this guards what
quantity an order CARRIES.

**The existing partial-close arm transfers and is not enough.** `T-0100` mapped MetaApi's
`close_position` as TWO calls — ticket-only and partial-by-volume — so an adapter must read
`lot_size` to dispatch between them, which `test_t0038_partial_close_contract` already
requires. **But that arm only ever proved the value is READ. It has never proved it is
CONVERTED**, and MetaApi's `volume` is MT5 lots while ours is units. `B167` one field over,
where the token is a number and the failure is an order for the wrong quantity.

**NO VENUE CONSTANT IS HARDCODED HERE EITHER.** The fixtures below are named for the shapes
they exercise, not for a broker's real table — those are per-instrument and broker-reported,
and nobody has connected to the venue.
"""
from __future__ import annotations

import pytest

from app.services.execution.lots import (
    BOUND_MAX,
    BOUND_MIN,
    BOUND_NON_POSITIVE,
    BOUND_STEP,
    units_to_lots,
)

#: A round-lot instrument. Shapes, not a broker's table.
FX = dict(contract_size=100_000.0, volume_min=0.01, volume_step=0.01, volume_max=100.0)
#: A step that does NOT divide the requested size evenly — the case floats get wrong.
COARSE = dict(contract_size=1.0, volume_min=0.1, volume_step=0.1, volume_max=10.0)


# ======================================================================================
# THE TABLE
# ======================================================================================

CASES = [
    # (label,              units,      kwargs, expect_lots, refused, bound,   clamped)
    ("a clean multiple",    150_000.0, FX, 1.5,   False, None,      False),
    ("exactly volume_min",    1_000.0, FX, 0.01,  False, None,      False),
    ("just below the min",      999.0, FX, None,  True,  BOUND_MIN, False),
    ("far below the min",       500.0, FX, None,  True,  BOUND_MIN, False),
    ("exactly volume_max", 10_000_000.0, FX, 100.0, False, None,    False),
    ("above volume_max",   20_000_000.0, FX, 100.0, False, None,    True),
    ("zero units",                 0.0, FX, None,  True,  BOUND_NON_POSITIVE, False),
    ("negative units",            -5.0, FX, None,  True,  BOUND_NON_POSITIVE, False),
    ("a step that does not divide", 0.35, COARSE, 0.3, False, None, False),
]


@pytest.mark.parametrize(
    "label,units,kw,lots,refused,bound,clamped", CASES, ids=[c[0] for c in CASES]
)
def test_the_conversion_table(label, units, kw, lots, refused, bound, clamped):
    r = units_to_lots(units, **kw)

    assert r.refused is refused, f"{label}: {r.reason}"
    assert r.bound == bound, label
    assert r.clamped is clamped, label
    if lots is None:
        assert r.lots is None, label
    else:
        assert r.lots == pytest.approx(lots, abs=1e-9), label


# ======================================================================================
# THE TWO FAILURES THAT COST MONEY RATHER THAN REPORTS
# ======================================================================================


@pytest.mark.parametrize("units", [0.0, 1.0, 100.0, 500.0, 999.0, 999.9999])
def test_it_NEVER_returns_zero_lots(units):
    """**`B221`'s shape.** A `0.0` lot order is rejected by the venue while the caller reports
    having placed one — *a success report over an action that did not happen.*

    Every sub-minimum size must come back as a REFUSAL carrying its bound, never as a number
    that reads as a placed order of no size.
    """
    r = units_to_lots(units, **FX)
    assert r.lots != 0.0, f"{units} units produced a zero-lot order"
    assert r.lots is None and r.refused is True
    assert r.bound in (BOUND_MIN, BOUND_NON_POSITIVE)
    assert r.reason, "a refusal with no reason cannot be reported honestly"


@pytest.mark.parametrize("units", [999.0, 950.0, 500.0, 100.0, 1.0])
def test_it_NEVER_rounds_UP_across_volume_min(units):
    """**The common case on a small account, and the one most likely to be got wrong.**

    Rounding up to reach the minimum takes MORE risk than the ruled percentage, and silently
    breaks the single property verified live twice — that a trade risks exactly 1%. *A
    refusal is correct; a slightly-too-big position is not.*
    """
    r = units_to_lots(units, **FX)
    assert r.refused is True and r.bound == BOUND_MIN
    assert r.lots is None, (
        f"{units} units was rounded up to {r.lots} lots to reach the {FX['volume_min']} "
        "minimum — that is a position the account was never sized for"
    )


def test_the_step_rounds_DOWN_and_never_up():
    """A broker rejects a volume that is not a whole multiple, so it must move — and the
    DIRECTION is the decision. Down risks slightly less than ruled; up risks more."""
    r = units_to_lots(149_999.0, **FX)
    assert r.lots == pytest.approx(1.49, abs=1e-9), (
        f"1.49999 lots became {r.lots}; rounding to 1.50 would take more than the ruled risk"
    )
    assert r.lots < r.requested_lots


def test_the_step_is_computed_in_DECIMAL_not_binary_floats():
    """`0.3 / 0.1` is `2.9999999999999996` in binary floats, which floors to 2 and **halves
    the order**. `B227` is the same hazard one module over; here it is a live size error
    rather than a misread record."""
    assert 0.3 / 0.1 != 3.0, "the float hazard this guards is real on this interpreter"

    r = units_to_lots(0.3, **COARSE)
    assert r.refused is False
    assert r.lots == pytest.approx(0.3, abs=1e-12), (
        f"0.3 units at a 0.1 step became {r.lots} — binary float division truncated a whole "
        "step off the order"
    )


# ======================================================================================
# THE CLAMP IS A SIZE REDUCTION AND MUST BE VISIBLE
# ======================================================================================


def test_a_clamp_is_RECORDED_and_is_not_a_refusal():
    """The order is placeable, so refusing would be wrong — but the caller asked for more than
    it got, and a caller that cannot see that reports a position it did not take."""
    r = units_to_lots(20_000_000.0, **FX)

    assert r.refused is False and r.lots == pytest.approx(100.0)
    assert r.clamped is True, "a silent clamp is a size the caller cannot know about"
    assert r.requested_lots == pytest.approx(200.0)
    assert r.reason and "clamped" in r.reason


def test_a_clamp_lands_on_a_whole_STEP_not_on_the_bare_maximum():
    """`volume_max` need not itself be a multiple of `volume_step`, and a broker rejects a
    volume that is not."""
    odd = dict(contract_size=1.0, volume_min=0.1, volume_step=0.3, volume_max=1.0)
    r = units_to_lots(50.0, **odd)

    assert r.clamped is True
    assert r.lots == pytest.approx(0.9, abs=1e-9), (
        f"clamped to {r.lots}, which is not a whole multiple of 0.3"
    )


# ======================================================================================
# MUST-MISS AND THE UNUSABLE INSTRUMENT
# ======================================================================================


@pytest.mark.parametrize(
    "kw", [dict(FX, contract_size=0.0), dict(FX, volume_step=0.0), dict(FX, volume_step=-1.0)]
)
def test_an_unusable_instrument_REFUSES_rather_than_dividing_by_zero(kw):
    r = units_to_lots(150_000.0, **kw)
    assert r.refused is True and r.bound == BOUND_STEP
    assert r.lots is None


def test_the_refusal_says_WHICH_bound_it_hit():
    """*A caller that cannot tell refused-because-too-small from refused-because-too-large
    cannot report either honestly.*"""
    too_small = units_to_lots(500.0, **FX)
    unusable = units_to_lots(150_000.0, **dict(FX, volume_step=0.0))

    assert too_small.bound == BOUND_MIN
    assert unusable.bound == BOUND_STEP
    assert too_small.bound != unusable.bound
    assert "below the instrument minimum" in too_small.reason
    assert "unusable" in unusable.reason


def test_size_position_is_UNTOUCHED_by_this_module():
    """`size_position` is correct and has been verified against live rows twice. This is a new
    function BESIDE it, and the conversion is the adapter's to wire."""
    import ast
    import inspect

    from app.services.execution import lots as lots_mod
    from app.services.execution.service import size_position

    # STRUCTURAL, NOT SUBSTRING — and this arm failed on its own first run for exactly that
    # reason. `lots.py`'s docstring NAMES `size_position` to say it is untouched, and a
    # substring check read the explanation as the coupling. **A mention is not a call.**
    # Third time this class has been caught in a guard of mine (`B245`, and the two repairs
    # in `T-0068` and `T-0084`), so it is written the right way round here.
    tree = ast.parse(inspect.getsource(lots_mod))
    couplings = [
        ast.unparse(n)[:80] for n in ast.walk(tree)
        if (isinstance(n, ast.Call) and "size_position" in ast.unparse(n.func))
        or (isinstance(n, (ast.Import, ast.ImportFrom)) and "size_position" in ast.unparse(n))
    ]
    assert not couplings, f"the conversion reaches into the sizer: {couplings}"

    # And the sizer itself still returns UNITS, unchanged.
    assert size_position(5000.0, 0.01, 70_000.0, 69_000.0) == pytest.approx(0.05, abs=1e-9)


# ======================================================================================
# T-0103 / `B283` — A REFUSAL MUST CARRY THE BOUND THAT *CAUSED* IT
#
# Three branches refused with `bound=BOUND_MIN` and only one was minimum-caused. **The
# accurate prose hid the inaccurate field:** the `volume_max` branch's reason string names
# `volume_max` and is correct, so a reader who checks the message finds the right cause and
# never looks at the field. *It survives a careful read and fails only where a caller
# BRANCHES rather than reads* — which is precisely what `T-0097` said the bound was for.
# ======================================================================================

#: An instrument whose own bounds leave NO legal volume: the largest multiple of the step at
#: or below the max is below the min. The refusal is caused by the MAXIMUM.
NO_LEGAL_VOLUME = dict(contract_size=1.0, volume_min=5.0, volume_step=0.3, volume_max=1.0)
#: A zero minimum, which makes the round-down-to-zero branch REACHABLE. The cause is the STEP.
ZERO_MIN = dict(contract_size=1.0, volume_min=0.0, volume_step=0.1, volume_max=10.0)


def test_the_max_caused_refusal_does_NOT_report_volume_min():
    r = units_to_lots(50.0, **NO_LEGAL_VOLUME)

    assert r.refused is True
    assert r.bound == BOUND_MAX, (
        f"a refusal caused by volume_max reported {r.bound!r}. Its own reason string names "
        "volume_max and is correct — which is what makes this survive a careful read."
    )
    assert "volume_max" in r.reason, "and the message must still name the real cause"


def test_the_step_caused_refusal_does_NOT_report_volume_min():
    """**Re-keyed even though it is unreachable while `volume_min > 0`.** A one-line fix to
    the max branch would have left the identical defect here for the day an instrument
    reports a zero minimum — and the comment saying it is unreachable is exactly what would
    stop anyone looking. With `volume_min = 0` it IS reachable, and this exercises it."""
    r = units_to_lots(0.05, **ZERO_MIN)

    assert r.refused is True
    assert r.bound == BOUND_STEP, f"a refusal caused by the step reported {r.bound!r}"
    assert r.lots is None, "and still never 0.0"


def test_every_refusal_branch_reports_a_DISTINCT_and_CORRECT_cause():
    """All four causes, side by side. *A caller that cannot tell them apart cannot report any
    of them honestly*, and three of them used to be the same token."""
    causes = {
        "below the minimum":       units_to_lots(500.0, **FX).bound,
        "bounds leave nothing":    units_to_lots(50.0, **NO_LEGAL_VOLUME).bound,
        "rounds down to zero":     units_to_lots(0.05, **ZERO_MIN).bound,
        "non-positive units":      units_to_lots(0.0, **FX).bound,
        "unusable instrument":     units_to_lots(1.0, **dict(FX, volume_step=0.0)).bound,
    }
    assert causes["below the minimum"] == BOUND_MIN
    assert causes["bounds leave nothing"] == BOUND_MAX
    assert causes["rounds down to zero"] == BOUND_STEP
    assert causes["non-positive units"] == BOUND_NON_POSITIVE
    assert causes["unusable instrument"] == BOUND_STEP
    assert len({causes["below the minimum"], causes["bounds leave nothing"]}) == 2, (
        "the min-caused and max-caused refusals must not share a token"
    )


# ======================================================================================
# `B261`'s OWN EXAMPLE — a lot meaning something else entirely
# ======================================================================================

#: A metals-shaped profile. `contract_size=100` is `B261`'s example of the same field name
#: carrying a different quantity, and the whole reason this conversion exists.
METALS = dict(contract_size=100.0, volume_min=0.01, volume_step=0.01, volume_max=50.0)


def test_a_metals_profile_converts_on_its_OWN_contract_size():
    """100 units is 1.00 lots here and 0.001 lots on the FX profile — **the same number of
    units, two different orders.** That is the failure this module exists to prevent, and it
    was previously absent from the table."""
    metals = units_to_lots(100.0, **METALS)
    fx = units_to_lots(100.0, **FX)

    assert metals.refused is False and metals.lots == pytest.approx(1.0, abs=1e-9)
    assert fx.refused is True and fx.bound == BOUND_MIN, (
        "100 units is below the FX minimum — the same units, a legal order on one instrument "
        "and a refusal on the other"
    )


def test_the_module_PUBLISHES_what_it_does_not_cover():
    """**`B240`.** Ten arms and a table over now-three profiles, and a coverage claim without
    its complement is the shape this register keeps finding.

    The assumption that matters most is the one that cannot be seen from inside: **if the
    three bounds are conventions WE picked rather than the broker's, the function is
    validating against itself.**
    """
    import inspect

    from app.services.execution import lots as lots_mod

    doc = inspect.getdoc(lots_mod) or ""
    assert "DOES NOT COVER" in doc
    assert "get_symbol_specification" in doc, (
        "the assumed SOURCE of the three bounds must be named — if they are ours, every "
        "refusal is correct with respect to numbers nobody at the venue ever stated"
    )
    assert "validating against itself" in doc
    assert "margin" in doc, "a legal volume can still be refused for margin"
