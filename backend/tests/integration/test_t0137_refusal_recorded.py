"""T-0137 — the refusal must be RECORDED and COUNTED, not merely refused.

A refusal that leaves no row is the silent drop, and it is the failure this task is really
about: **every arm asserting "no order was placed" stays green under it.** Those arms certify
nothing on their own — the venue refused and the record is empty look identical from there.

**THE COUNT IS A QUERY, NOT A FIELD.** `_record_rejected_signal` already writes `signal_dir`
and `outcome=REJECTED`, so `GROUP BY signal_dir` answers *how many shorts were refused* off rows
that exist. A counter incremented beside them would be a second representation of the same fact
(`B184`) and would drift from the rows the first time one path wrote without the other.

*Integration rather than unit: the subject is a row surviving a real insert and a real query.
`signal_dir` is closed by a CHECK constraint, and a value the constant allows and the database
refuses is exactly what only an insert can tell apart (`T-0084`'s reason, unchanged).*
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.db.enums import DirectionType
from app.models.decision_record import (
    COHORT_PAPER, OUTCOME_REJECTED, DecisionRecord,
)
from app.services.broker.alpaca import ALPACA_CRYPTO_LONG_ONLY
from app.services.broker.paper import PaperBroker
from app.services.execution.service import ExecMode, ExecutionService, Signal
from app.services.live.crypto_loop import LiveCryptoLoop

pytestmark = pytest.mark.asyncio

BTC = "BTC/USD"


@pytest.fixture
async def bound(engine, monkeypatch):
    """Point the loop's own session maker at the test database."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    monkeypatch.setattr(dbsession, "AsyncSessionLocal", maker)
    return maker


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2026-09-10", periods=12, freq="5min", tz="UTC")
    return pd.DataFrame(
        {"open": 70_000.0, "high": 70_100.0, "low": 69_900.0, "close": 70_050.0, "volume": 1.0},
        index=idx,
    )


def _signal(direction: DirectionType) -> Signal:
    sl = 69_000.0 if direction == DirectionType.LONG else 71_000.0
    return Signal(symbol=BTC, direction=direction, entry=70_000.0, sl=sl, approved=True)


async def _refuse_for_real(direction: DirectionType) -> dict:
    """The refusal produced by the ACTUAL execution path, not a hand-written string.

    `B368`/`B369`: drive the producer. A literal reason typed into this file would keep this
    arm green after the venue's sentence changed, which is the one thing it exists to notice.
    """
    broker = PaperBroker(starting_balance=10_000.0, price_fn=lambda p: 70_000.0,
                         direction_policy=ALPACA_CRYPTO_LONG_ONLY)
    broker.on_tick(BTC, 70_000.0)
    return await ExecutionService(broker, ExecMode.PAPER).execute(_signal(direction))


# =====================================================================================
# M-2 — THE ROW EXISTS, AND IT CARRIES THE VENUE'S REASON AND ITS DIRECTION
# =====================================================================================

async def test_a_venue_refusal_is_written_as_a_REJECTED_row_with_the_venue_reason(bound):
    """**The arm M-4's mutation must kill.** Refuse the short and drop the record silently, and
    every "no order was placed" assertion elsewhere survives — this one does not.
    """
    res = await _refuse_for_real(DirectionType.SHORT)
    assert res["status"] != "FILLED"

    loop = LiveCryptoLoop()
    await loop._record_rejected_signal(
        BTC, _bars(), _signal(DirectionType.SHORT), res["reason"],
        SimpleNamespace(reasons=["FVG entry", "bias aligned"]),
    )

    async with bound() as db:
        rows = list((await db.execute(select(DecisionRecord))).scalars().all())

    assert len(rows) == 1, "the refusal left no trace at all — the silent drop"
    row = rows[0]
    assert row.outcome == OUTCOME_REJECTED
    assert row.signal_dir == "SHORT", "without the direction the split cannot be computed"
    assert row.abstained is False, "the detector FIRED; abstained would erase that"
    assert row.rejection_reason == ALPACA_CRYPTO_LONG_ONLY.reason, (
        "the venue's sentence must survive the trip into the record unaltered"
    )
    assert "alpaca" in row.rejection_reason.lower()
    assert row.cohort == COHORT_PAPER
    assert row.sized_units is None and row.fill_price is None, (
        "there was no fill; either number would be one nobody observed"
    )


async def test_a_venue_refusal_is_distinguishable_from_a_DRIFT_rejection_by_its_reason(bound):
    """Both are `outcome=REJECTED` with a direction. **Only `rejection_reason` separates
    a permanent venue rule from a bar-specific one**, which is why the reason has to name the
    constraint rather than restate the refusal.
    """
    venue = await _refuse_for_real(DirectionType.SHORT)
    loop = LiveCryptoLoop()
    await loop._record_rejected_signal(
        BTC, _bars(), _signal(DirectionType.SHORT), venue["reason"],
        SimpleNamespace(reasons=[]),
    )
    await loop._record_rejected_signal(
        BTC, _bars(), _signal(DirectionType.SHORT),
        "price moved 3.10R from the signal entry (70000.00 -> 69000.00); limit 1.00R",
        SimpleNamespace(reasons=[]),
    )

    async with bound() as db:
        rows = list((await db.execute(select(DecisionRecord))).scalars().all())

    assert len(rows) == 2
    reasons = {r.rejection_reason for r in rows}
    assert len(reasons) == 2, "two different refusals collapsed into one sentence"
    assert sum("not shortable" in r.rejection_reason for r in rows) == 1, (
        "a count of venue refusals that matched every rejection would overstate the ruling's "
        "cost, and one that matched none would hide it"
    )


# =====================================================================================
# M-3 — THE COUNT, AS A `GROUP BY` OVER ROWS THAT ALREADY EXIST
# =====================================================================================

async def test_the_refusals_are_COUNTABLE_by_direction_with_a_GROUP_BY(bound):
    """No counter is added anywhere. This is the query that answers *how many shorts were
    refused*, run against the rows the loop writes."""
    loop = LiveCryptoLoop()
    run_id = await loop.ensure_run()
    res = await _refuse_for_real(DirectionType.SHORT)

    for _ in range(3):
        await loop._record_rejected_signal(
            BTC, _bars(), _signal(DirectionType.SHORT), res["reason"],
            SimpleNamespace(reasons=[]),
        )
    await loop._record_rejected_signal(
        BTC, _bars(), _signal(DirectionType.LONG), "non-positive size / stop",
        SimpleNamespace(reasons=[]),
    )

    async with bound() as db:
        split = dict((await db.execute(
            select(DecisionRecord.signal_dir, func.count(DecisionRecord.id))
            .where(DecisionRecord.run_id == run_id,
                   DecisionRecord.outcome == OUTCOME_REJECTED)
            .group_by(DecisionRecord.signal_dir)
        )).all())

    assert split == {"SHORT": 3, "LONG": 1}


async def test_the_runs_endpoint_SURFACES_the_split_beside_the_PnL(bound, client, monkeypatch):
    """**WHERE THE COUNT HAS TO APPEAR, AND WHY IT IS THIS SURFACE.**

    `B380`'s lesson is not *"write it to a surface"* — it is *drive the witness from the layer
    where the wrong conclusion would be drawn*. The misreading is **"the strategy
    underperformed"**, and that is read off P&L and win rate. This endpoint carries both. A run
    that produced no shorts and a run that had 147 refused have the same P&L and the same trade
    list, so without the split beside those numbers this surface can state the wrong conclusion
    with nothing next to it to qualify the figure.
    """
    loop = LiveCryptoLoop()
    run_id = await loop.ensure_run()
    res = await _refuse_for_real(DirectionType.SHORT)
    for _ in range(2):
        await loop._record_rejected_signal(
            BTC, _bars(), _signal(DirectionType.SHORT), res["reason"],
            SimpleNamespace(reasons=[]),
        )

    from app.api.routers import engine as engine_router
    monkeypatch.setattr(engine_router, "_loop", lambda _req: loop)

    rows = (await client.get("/api/engine/runs")).json()
    row = next(r for r in rows if r["id"] == str(run_id))

    assert row["rejected_by_direction"] == {"SHORT": 2}, (
        "the split must be PARTITIONED — a bare total cannot answer which direction was lost"
    )
    assert row["rejections"] == 2
    assert "realized_pnl" in row and "wins" in row, (
        "the split is only load-bearing while it sits beside the numbers that get misread"
    )


async def test_the_run_config_MARKS_the_run_as_long_only(bound):
    """`EngineRun.config` is snapshotted at start *"so a result can never be read against the
    wrong settings later"*. Long-only is such a setting, and a stronger one than most: it does
    not shrink the sample, it changes the strategy.

    Any surface that already renders a run's config is then self-marking, at the cost of one
    dict entry rather than a new column.
    """
    from app.models.engine_run import EngineRun

    loop = LiveCryptoLoop()
    run_id = await loop.ensure_run()

    async with bound() as db:
        run = (await db.execute(select(EngineRun).where(EngineRun.id == run_id))).scalar_one()

    assert run.config["long_only"] is True
    assert run.config["venue"] == "alpaca"

    # `records_rejected_signals` is checked BELOW ITS OWN WEIGHT, deliberately.
    #
    # It is a hardcoded `True` written at snapshot time, before a single signal has been
    # refused, and nothing in the tree reconciles it against the rows. **A flag we wrote is a
    # claim; a row you can query is evidence** — so reading it back is checking our own
    # paperwork, and it is asserted here only to catch the config being dropped entirely.
    #
    # The failure it PERMITS is the one this task exists to prevent: if the recording path is
    # unwired or swallows its error, this key still says `True`, every downstream reader
    # believes the run's rejections are complete, and 147 missing shorts are an absence the
    # config actively certifies as healthy. The arms that carry the weight are the ones above,
    # which query the records themselves.
    assert run.config["records_rejected_signals"] is True, (
        "the config snapshot is no longer being persisted at all"
    )


async def test_the_config_mark_is_DERIVED_from_the_broker_the_run_executes_against(bound):
    """**A literal `True` would keep claiming long-only after the policy changed.** A config
    that describes a run it did not govern is worse than one that says nothing — `B238`'s
    class, and this file has shipped that defect before.
    """
    loop = LiveCryptoLoop()
    assert loop._config_snapshot()["long_only"] is True

    loop.paper.direction_policy = None
    assert loop._config_snapshot()["long_only"] is False, (
        "the snapshot ignored the broker it was reading and asserted a constant"
    )
    assert loop._config_snapshot()["venue"] is None


async def test_the_venue_policy_SURVIVES_A_RESET(bound):
    """**THE SECOND CONSTRUCTION SITE, WHICH IS INVISIBLE FROM THE FIRST.**

    Every piece of this wiring lives at two places: the initialiser and `_reset_broker_state`,
    which REBUILDS the broker from scratch when a run is reset. A policy passed at one and
    forgotten at the other leaves a suite fully green and an engine that enforces long-only
    until the first reset and silently stops afterwards — and a reset is a button on the
    dashboard, not a rare event.

    The mark in the config would keep saying `long_only: true` the whole time, which is what
    makes this failure quiet rather than loud.
    """
    loop = LiveCryptoLoop()
    assert loop.paper.direction_policy is ALPACA_CRYPTO_LONG_ONLY

    before = id(loop.paper)
    await loop._reset_broker_state()

    assert id(loop.paper) != before, "the broker was not actually rebuilt; the arm proves nothing"
    assert loop.paper.direction_policy is ALPACA_CRYPTO_LONG_ONLY, (
        "the rebuilt broker lost the venue constraint — shorts fill again after a reset"
    )
    assert loop.execution.broker is loop.paper, (
        "execution is still holding the OLD broker, so the policy on the new one is unreachable"
    )
    # And it actually refuses, rather than merely carrying the attribute.
    #
    # THE MARK GOES ON THE LOOP, NOT ON THE BROKER, and the difference is not cosmetic: the
    # rebuilt `SimPropFirmBroker` gets a `_price_source` closure that reads `loop._marks`, so
    # priming the broker's own marks leaves `reference_price` at 0 and `execute()` returns
    # `status="rejected"` for *"no reference price available"* — a refusal that never reaches
    # the venue check at all. An arm written that way measures the price source and reports
    # the venue.
    loop._marks[BTC] = 70_000.0
    loop.paper.on_tick(BTC, 70_000.0)
    res = await loop.execution.execute(_signal(DirectionType.SHORT))
    assert res["status"] == "REJECTED", (
        f"expected the venue refusal; got {res.get('reason')!r}"
    )
    assert res["reason"] == ALPACA_CRYPTO_LONG_ONLY.reason


# =====================================================================================
# THE ROUTING — STRUCTURAL, BECAUSE THE ENCLOSING METHOD CANNOT BE DRIVEN CHEAPLY
# =====================================================================================

async def test_the_loop_ROUTES_a_non_filled_execution_into_the_rejection_recorder():
    """**WHAT THIS COVERS AND WHAT IT DOES NOT — stated, because the gap is the interesting
    half.**

    The arms above drive `_record_rejected_signal` itself with a reason produced by a real
    refusal. What they do NOT drive is the four-line `else` branch in `_tick_symbol` that
    connects the two: that method fetches a live ticker price, pulls 320 bars and runs the
    strategy, so driving it here would be a network test wearing a unit test's clothes.

    **So the connection is asserted structurally instead**, over the AST rather than the text:
    the branch taken when execution does not FILL must call `_record_rejected_signal`, and must
    pass it a reason read off the execution result rather than a literal. Swallowing that call
    — M-2's mutation — deletes the node this reads.

    A substring search would not do: `_record_rejected_signal` appears in this file's own
    docstrings, and a scan keyed on a word the subject chose returns a confident zero the day
    the subject rewords it.
    """
    src = Path(inspect.getfile(LiveCryptoLoop)).read_text()
    tree = ast.parse(src)

    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_tick_symbol"
    )
    fork = next(
        n for n in ast.walk(fn)
        if isinstance(n, ast.If)
        and any(
            isinstance(c, ast.Constant) and c.value == "FILLED"
            for c in ast.walk(n.test)
        )
    )
    assert fork.orelse, "the non-FILLED branch is gone; a refused signal now falls through"

    calls = [
        n for n in ast.walk(ast.Module(body=fork.orelse, type_ignores=[]))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_record_rejected_signal"
    ]
    assert len(calls) == 1, (
        "the non-FILLED branch does not record the refusal — every 'no order was placed' "
        "assertion in the suite stays green while the evidence is dropped"
    )

    # The reason must be a NAME bound in that branch, not a literal: `reason = res.get(...)`.
    assert any(isinstance(a, ast.Name) for a in calls[0].args), (
        "the recorder is called with a hard-coded reason, so the venue's sentence never "
        "reaches the record"
    )
    assigned = {
        t.id
        for n in ast.walk(ast.Module(body=fork.orelse, type_ignores=[]))
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    assert "reason" in assigned, "the branch no longer derives a reason from the result"


# =====================================================================================
# T-0138 — THE RUN REFUSES TO START AGAINST A VENUE THAT CANNOT PLACE AN ORDER
# =====================================================================================

async def test_a_run_REFUSES_TO_START_when_the_venue_cannot_place_orders(bound):
    """**ONE REFUSAL BEFORE THE RUN EXISTS, NOT 146 AFTERWARDS.**

    `place_order`'s body is part D's, so a run pointed at Alpaca today would fail every entry
    individually — and an operator reading a wall of venue errors concludes the VENUE is down and
    goes to debug Alpaca. `B380`'s shape with the diagnosis relocated.

    **And the refusal must happen BEFORE `reset_run`.** Refusing after it would have already ended
    the previous run and opened a new one, so a rejected start would destroy the run it declined
    to replace — the reset is not a no-op just because the start failed.
    """
    loop = LiveCryptoLoop()
    first_run = await loop.ensure_run()

    class CannotPlace(PaperBroker):
        def order_path_status(self) -> str | None:
            return "the order path is not written yet — part D of ALPACA_PROGRAMME.md"

    loop.paper = CannotPlace(starting_balance=5_000.0, price_fn=lambda p: 70_000.0)

    result = await loop.start()

    assert result.get("started") is False
    assert "part D" in result["refused"], "the refusal must name the task that owns the body"
    assert loop._running is False, "the loop started anyway; the gate is decorative"
    assert loop.run_id == first_run, (
        "the refused start ENDED the previous run and opened a new one — a rejected start must "
        "not be destructive"
    )


async def test_the_gate_is_ASKED_OF_THE_ADAPTER_and_does_not_block_the_simulators(bound):
    """**The control, and it is the one that matters operationally**: a gate keyed on the venue's
    name rather than on the adapter's own answer would still be refusing runs the day after part D
    wrote the body. Worse, a gate that blocks everything stops the platform.
    """
    loop = LiveCryptoLoop()
    assert loop.paper.order_path_status() is None, (
        "the production simulator must remain startable — this is the engine's live path"
    )
