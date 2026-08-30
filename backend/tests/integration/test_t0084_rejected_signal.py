"""T-0084 — `B271`: a signal the strategy PRODUCED and execution REFUSED had nowhere to go.

Neither existing writer could take the row. `_record_signal_decision` asserts `OPEN` with
`sized_units`, `fill_price` and `expected_r` **from a fill this bar does not have**;
`_record_abstention` asserts `abstained=True, outcome=ABSTAINED` — **and the strategy DID
produce a signal.**

**`ABSTAINED` WAS THE TEMPTING OPTION AND THE DANGEROUS ONE.** It makes a bar where the
strategy committed indistinguishable from one where the detector never fired — `B215`'s
could-not-versus-did-not collapse, rebuilt **inside the one population that is currently
correct**, which is `B268`'s denominator.

*Integration, not unit, because the CHECK constraint is the subject: a value the constant
allows and the database refuses is exactly the failure this migration exists to prevent, and
only a real insert can tell them apart.*
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.decision_record import (
    DECISION_OUTCOMES,
    OUTCOME_ABSTAINED,
    OUTCOME_REJECTED,
    DecisionRecord,
)

pytestmark = pytest.mark.asyncio


async def _insert(db, **kw) -> DecisionRecord:
    rec = DecisionRecord(
        symbol="BTC/USD", timeframe="5m", inputs_hash="i", code_path_hash="c",
        cohort="paper", **kw,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return rec


async def test_a_rejected_signal_row_is_ACCEPTED_by_the_check_constraint(db_session):
    """The migration's whole point. `outcome` is closed by a CHECK, so a new value is a
    schema change — and a constant that allows what the database refuses would be a green
    unit test over an insert that cannot happen."""
    rec = await _insert(
        db_session,
        outcome=OUTCOME_REJECTED,
        abstained=False,
        rejection_reason="price moved 3.10R from the signal entry (70000.00 -> 69000.00)",
    )
    assert rec.outcome == OUTCOME_REJECTED
    assert rec.rejection_reason.startswith("price moved 3.10R")


async def test_a_REJECTED_row_is_distinguishable_from_an_ABSTAINED_one_BY_VALUE(db_session):
    """**Not by absence — by value.** A reader must not have to infer which happened from
    which fields are empty."""
    rejected = await _insert(
        db_session, outcome=OUTCOME_REJECTED, abstained=False,
        rejection_reason="market 68000.00 is already through the stop 69000.00",
        signal_dir="LONG",
    )
    abstained = await _insert(db_session, outcome=OUTCOME_ABSTAINED, abstained=True)

    assert rejected.outcome != abstained.outcome
    assert rejected.abstained is False and abstained.abstained is True, (
        "`abstained` keeps the two apart even for a reader who does not know REJECTED exists"
    )
    assert rejected.signal_dir is not None and abstained.signal_dir is None, (
        "the strategy COMMITTED on the rejected bar — that is the fact ABSTAINED would erase"
    )

    rows = (await db_session.execute(
        select(DecisionRecord).where(DecisionRecord.outcome == OUTCOME_REJECTED)
    )).scalars().all()
    assert [r.id for r in rows] == [rejected.id], "a query for rejections must not return abstentions"


async def test_the_rejection_reason_is_stored_RAW_and_not_classified(db_session):
    """The five rejection sites split THREE ordinary market conditions against TWO producer
    defects. *A corpus that cannot tell a market condition from a fault rebuilds `B215` in a
    second place*, and a classification chosen now would fix that split before anyone has
    counted it."""
    market_condition = "no reference price available; refusing to size a market order"
    producer_defect = "non-positive size / stop"

    a = await _insert(db_session, outcome=OUTCOME_REJECTED, abstained=False,
                      rejection_reason=market_condition)
    b = await _insert(db_session, outcome=OUTCOME_REJECTED, abstained=False,
                      rejection_reason=producer_defect)

    assert a.rejection_reason == market_condition, "stored verbatim, not bucketed"
    assert b.rejection_reason == producer_defect
    assert a.rejection_reason != b.rejection_reason, (
        "a collapsed classification would make these two the same row, and one is the market "
        "behaving and the other is us being wrong"
    )


async def test_the_reason_has_a_COLUMN_rather_than_a_line_in_reasons(db_session):
    """`reasons` is *"a JSON list nothing parses"* by its own docstring, and the field `B270`
    criticised `B268` for parsing. Putting the reason only there would recreate the problem in
    the change that fixes it."""
    rec = await _insert(
        db_session, outcome=OUTCOME_REJECTED, abstained=False,
        rejection_reason="non-positive size / stop",
        reasons=["PASS history: 320 bars", "OBSERVED entry_rule_comparison: ..."],
    )
    assert rec.rejection_reason == "non-positive size / stop"
    assert not any("non-positive" in line for line in rec.reasons), (
        "the reason must be readable WITHOUT parsing free text"
    )


async def test_REJECTED_is_in_the_closed_vocabulary_and_is_its_OWN_value():
    assert OUTCOME_REJECTED in DECISION_OUTCOMES
    assert OUTCOME_REJECTED != OUTCOME_ABSTAINED
    assert len(set(DECISION_OUTCOMES)) == len(DECISION_OUTCOMES), "no duplicate outcomes"


# ======================================================================================
# `B279` + `B280` — THE THREE SIZING INPUTS, AND THE RECONSTRUCTION
#
# `size_position(acct.equity, sig.risk_pct, sizing_price, sig.sl)` takes FOUR arguments and
# THREE of them were recorded nowhere. `prop_firm_snapshots` has an equity column and ZERO
# rows, so the number a trade was sized against had never been persisted.
#
# **THE DIVISOR IS `sizing_price`, NOT `fill`, AND THAT IS `B280`.** A reconstruction using
# the fill is exact only where both come from the same cached mark — a property of
# `PaperBroker`, not of the system. Measured: 50 ticks of slip puts the recomputed size
# **4.76%** out, and nothing in the row says it happened. *`fill_price` exists as a separate
# column precisely because they are not the same thing.*
# ======================================================================================

from decimal import Decimal  # noqa: E402

from app.models.decision_record import OUTCOME_OPEN  # noqa: E402
from app.services.execution.service import size_position  # noqa: E402

#: The equity figure whose fourth decimal is the reason `Numeric(14, 2)` was not enough.
EQUITY, RISK_PCT, SIZING_PRICE, STOP = 5000.9197, 0.01, 70000.0, 69000.0


async def test_a_reader_can_RECOMPUTE_sized_units_from_the_rows_own_columns(db_session):
    """**The point of the change.** A row written after this must be self-sufficient.

    Tolerance is keyed to the STORED precision — `sized_units` is `Numeric(18, 6)`, so the
    reconstruction agrees to 1e-6 and exact equality would be flaky on the seventh place.
    """
    units = size_position(EQUITY, RISK_PCT, SIZING_PRICE, STOP)
    rec = await _insert(
        db_session, outcome=OUTCOME_OPEN, abstained=False, signal_dir="LONG",
        signal_sl=Decimal(str(STOP)),
        fill_price=Decimal("70050.000000"),          # SLIPPED, deliberately
        sized_units=Decimal(str(round(units, 6))),
        sizing_equity=Decimal(str(EQUITY)),
        sizing_risk_pct=Decimal(str(RISK_PCT)),
        sizing_price=Decimal(str(SIZING_PRICE)),
    )

    recomputed = (
        float(rec.sizing_equity) * float(rec.sizing_risk_pct)
        / abs(float(rec.sizing_price) - float(rec.signal_sl))
    )
    assert recomputed == pytest.approx(float(rec.sized_units), abs=1e-6)


async def test_the_divisor_is_sizing_price_and_using_the_FILL_would_be_WRONG(db_session):
    """**`B280`, as a measurement rather than a claim.**

    The row above carries a fill 50 ticks away from the price the size was computed at. The
    reconstruction that uses `fill` does not reproduce `sized_units` — and it does not fail
    loudly, *it just comes out wrong by exactly the slippage.*
    """
    units = size_position(EQUITY, RISK_PCT, SIZING_PRICE, STOP)
    rec = await _insert(
        db_session, outcome=OUTCOME_OPEN, abstained=False, signal_dir="LONG",
        signal_sl=Decimal(str(STOP)), fill_price=Decimal("70050.000000"),
        sized_units=Decimal(str(round(units, 6))),
        sizing_equity=Decimal(str(EQUITY)), sizing_risk_pct=Decimal(str(RISK_PCT)),
        sizing_price=Decimal(str(SIZING_PRICE)),
    )

    with_fill = (
        float(rec.sizing_equity) * float(rec.sizing_risk_pct)
        / abs(float(rec.fill_price) - float(rec.signal_sl))
    )
    assert with_fill != pytest.approx(float(rec.sized_units), abs=1e-6), (
        "if the fill reproduces the size here, the fixture stopped slipping and this arm "
        "has lost its subject"
    )
    error = abs(with_fill - float(rec.sized_units)) / float(rec.sized_units)
    assert error > 0.04, f"50 ticks should put it ~4.8% out, got {error:.4%}"


# `T-0098`/`B282`. **A must-hit stood here and it could never fail.** It INSERTED the row it
# then asserted existed — `assert rows` over a population the arm had just written — so it was
# green by construction, inside the arm requested specifically to prevent vacuity. `B272`'s
# fourth instance.
#
# **DELETED RATHER THAN RE-POINTED, and the reason is that re-pointing is not possible here.**
# The model cited when it was written was `test_there_are_adapters_to_check`, and what makes
# that arm work is that its population is DERIVED FROM THE TREE. This suite runs against a
# fresh per-test database, so the only rows in existence are the ones the test creates: *there
# are no rows it did not write to point at.*
#
# **Its job is done by an arm that CAN fail** — `test_decision_record_schema.py`'s
# `test_the_producer_passes_ALL_THREE_sizing_inputs_at_its_call_site` and
# `test_none_of_the_three_is_bound_to_a_LITERAL_None`, which read the producer's call site by
# AST. Measured: the mutation that nulls all three sizing arguments left this suite at
# `17 passed`, and fails the AST arm.
#
# *Recorded here so a later reader does not restore it.*


async def test_the_precision_carries_the_FOURTH_decimal(db_session):
    """`Numeric(14, 2)` would have rounded `5000.9197` to `5000.92`, and the finding this
    preserves lived in that fourth place — `5000.9197` against `5000.00`."""
    rec = await _insert(
        db_session, outcome=OUTCOME_OPEN, abstained=False,
        sizing_equity=Decimal("5000.919700"), sizing_risk_pct=Decimal("0.010000"),
        sizing_price=Decimal(str(SIZING_PRICE)),
    )
    assert float(rec.sizing_equity) == pytest.approx(5000.9197, abs=1e-6)

    # GATE-032's smallest ratified cell must survive the risk column's scale.
    fine = await _insert(
        db_session, outcome=OUTCOME_OPEN, abstained=False,
        sizing_risk_pct=Decimal("0.002500"),
    )
    assert float(fine.sizing_risk_pct) == pytest.approx(0.0025, abs=1e-9)
