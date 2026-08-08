"""Start, Pause and Stop are the whole engine control surface now.

The engine page used to ask for symbols, timeframes, broker, price source and a
starting balance before a run could begin, and it started itself on every boot
whether or not anyone had asked. Both are gone: the settings are frozen in
`services/live/fixed_config.py`, and the engine is idle until someone presses
Start.

That makes three properties load-bearing, and each one is a way the old design
could lie about what had happened:

  * **A fresh boot is stopped.** A deploy at 3am must not resume taking
    decisions with nobody watching.
  * **Start opens a NEW run.** Adopting an open one is KNOWN_ISSUES A9 — the
    loop carried on writing into a run whose stored config no longer described
    the trades beneath it.
  * **Stop leaves nothing unresolved.** A stopped engine marks no prices, so an
    open position's stop-loss would never be checked again. It is not still
    open; it is abandoned, and the run's result is short one trade.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest
from app.models.engine_run import EngineRun
from app.services.live import fixed_config as fixed
from app.services.live.crypto_loop import LiveCryptoLoop

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bound(engine, monkeypatch):
    """Point the loop's own session maker at the test database."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    monkeypatch.setattr(dbsession, "AsyncSessionLocal", maker)
    return maker


@pytest.fixture
def quiet(monkeypatch):
    """Start the lifecycle without starting the scanner.

    The loop body polls Binance. These tests are about Start/Stop bookkeeping,
    and a real network call inside them would make the assertions depend on an
    exchange being reachable.
    """
    async def noop(self):
        return None

    monkeypatch.setattr(LiveCryptoLoop, "_loop", noop)


async def open_runs(maker) -> list[EngineRun]:
    async with maker() as db:
        return list((await db.execute(
            select(EngineRun).where(EngineRun.ended_at.is_(None))
        )).scalars().all())


# ---------------------------------------------------------------------------
# Idle until asked
# ---------------------------------------------------------------------------
async def test_a_fresh_engine_is_not_running(bound):
    """Constructing the loop must not start it. main.py builds one on every boot
    — if construction started scanning, "no autostart" would be a comment rather
    than a behaviour."""
    loop = LiveCryptoLoop()
    assert loop._running is False
    assert loop._task is None
    assert (await loop.status())["running"] is False


async def test_status_works_before_the_engine_has_ever_started(bound):
    """The page loads before anything is running. A status call that needs a
    started engine would render the whole panel as a failure on first visit."""
    st = await LiveCryptoLoop().status()
    assert st["running"] is False
    assert st["starting_balance"] == fixed.STARTING_BALANCE


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
async def test_start_opens_a_run_and_reports_running(bound, quiet):
    loop = LiveCryptoLoop()
    st = await loop.start()

    assert st["running"] is True
    assert loop.run_id is not None
    assert len(await open_runs(bound)) == 1


async def test_start_opens_a_NEW_run_and_closes_one_left_open(bound, quiet):
    """A crash leaves a run open. Resuming into it is A9: the engine writes
    hours of new decisions under a row that claims to describe an unbroken
    session, with no record of the gap in the middle."""
    async with bound() as db:
        orphan = EngineRun(config={"note": "killed container"}, note="interrupted")
        db.add(orphan)
        await db.commit()
        await db.refresh(orphan)
        orphan_id = orphan.id

    loop = LiveCryptoLoop()
    await loop.start()

    assert loop.run_id != orphan_id, "adopted the interrupted run instead of opening one"
    still_open = await open_runs(bound)
    assert [r.id for r in still_open] == [loop.run_id]

    async with bound() as db:
        was = (await db.execute(
            select(EngineRun).where(EngineRun.id == orphan_id)
        )).scalar_one()
        assert was.ended_at is not None, "the interrupted run was left open"


async def test_pressing_start_twice_does_not_abandon_the_first_run(bound, quiet):
    """The second press is a mis-click, not a request for a new run. Opening one
    would silently end a run that was doing exactly what was asked of it."""
    loop = LiveCryptoLoop()
    await loop.start()
    first = loop.run_id

    await loop.start()

    assert loop.run_id == first
    assert len(await open_runs(bound)) == 1


async def test_a_started_run_records_the_frozen_settings(bound, quiet):
    """The run's config is the record of what produced its trades. It has to be
    the real settings, read from the same module the engine reads."""
    loop = LiveCryptoLoop()
    await loop.start()

    async with bound() as db:
        row = (await db.execute(
            select(EngineRun).where(EngineRun.id == loop.run_id)
        )).scalar_one()

    assert row.config["symbols"] == list(fixed.SYMBOLS)
    assert row.config["entry_tf"] == fixed.ENTRY_TF
    assert row.config["broker_mode"] == fixed.BROKER_MODE
    assert row.config["starting_balance"] == fixed.STARTING_BALANCE
    assert row.config["risk_pct"] == fixed.RISK_PCT


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------
async def test_stop_ends_the_run_and_stops_scanning(bound, quiet):
    loop = LiveCryptoLoop()
    await loop.start()
    st = await loop.stop()

    assert st["running"] is False
    assert loop._task is None
    assert await open_runs(bound) == []


async def test_stop_closes_open_positions_rather_than_abandoning_them(bound, quiet):
    """A stopped engine marks no prices. A position left open would sit at
    whatever it was worth the moment the engine stopped, its stop-loss never
    checked again, and the run's result would be missing a trade."""
    loop = LiveCryptoLoop()
    await loop.start()

    loop._marks["BTC/USD"] = 100.0
    await loop.paper.place_order(OrderRequest(
        pair="BTC/USD", direction=DirectionType.LONG, order_type=OrderType.MARKET,
        lot_size=1.0, price=100.0, sl=90.0, tp=120.0,
    ))
    assert (await loop.paper.get_account()).open_trade_count == 1

    await loop.stop()

    assert (await loop.paper.get_account()).open_trade_count == 0


async def test_stopping_an_already_stopped_engine_is_harmless(bound, quiet):
    """Double-clicking Stop must not end a run that a later Start opened, nor
    raise at the user for pressing a button that was already in that state."""
    loop = LiveCryptoLoop()
    await loop.start()
    await loop.stop()
    st = await loop.stop()
    assert st["running"] is False


async def test_stop_then_start_gives_two_runs_in_the_history(bound, quiet):
    """The point of ending a run rather than pausing it: each Start/Stop cycle
    is one self-contained result you can compare against another."""
    loop = LiveCryptoLoop()
    await loop.start()
    first = loop.run_id
    await loop.stop()
    await loop.start()

    assert loop.run_id != first
    async with bound() as db:
        all_runs = list((await db.execute(select(EngineRun))).scalars().all())
    assert len(all_runs) == 2
    assert {r.id for r in all_runs} == {first, loop.run_id}


# ---------------------------------------------------------------------------
# Pause is not Stop
# ---------------------------------------------------------------------------
async def test_pause_keeps_the_run_open(bound, quiet):
    """Pause is for stepping away. If it ended the run, every coffee break would
    fragment the results into pieces too small to judge."""
    loop = LiveCryptoLoop()
    await loop.start()
    run = loop.run_id

    loop.paused = True
    st = await loop.status()

    assert st["running"] is True and st["paused"] is True
    assert loop.run_id == run
    assert len(await open_runs(bound)) == 1


async def test_a_paused_engine_refuses_entries(bound, quiet):
    """The pause flag has to reach the decision path, not only the label."""
    loop = LiveCryptoLoop()
    await loop.start()
    loop.paused = True
    assert await loop._entry_block_reason("BTC/USD") == "engine paused"


# ---------------------------------------------------------------------------
# The settings themselves
# ---------------------------------------------------------------------------
async def test_the_engine_runs_the_frozen_configuration(bound):
    """The defaults ARE the configuration. If the loop's defaults drift from
    fixed_config, the page shows one thing and the engine does another."""
    loop = LiveCryptoLoop()
    assert list(loop.symbols) == list(fixed.SYMBOLS)
    assert loop.entry_tf == fixed.ENTRY_TF
    assert loop.bias_tf == fixed.BIAS_TF
    assert loop.starting_balance == fixed.STARTING_BALANCE
    assert loop.broker_mode == fixed.BROKER_MODE
    assert loop.price_source_name == fixed.PRICE_SOURCE


async def test_risk_is_one_percent_and_is_not_a_knob(bound):
    """Pre-registered. ROI = risk_pct x n x avg_R is an identity, so changing it
    rescales the equity curve and the drawdown together — it cannot make a
    strategy better, only louder."""
    assert fixed.RISK_PCT == 0.01
    assert LiveCryptoLoop().risk_pct == 0.01


async def test_the_starting_balance_is_a_round_challenge_size(bound):
    """Prop-firm limits are percentages of the size you BOUGHT. Seeding from a
    live balance would move the drawdown allowance every time the account moved,
    so a breach would be measured against a base that had already shifted with
    it — which is why PropFirmRules refuses a real balance in its own docstring."""
    assert fixed.STARTING_BALANCE == 5_000.0
    assert fixed.STARTING_BALANCE % 1000 == 0, "not a round challenge size"


async def test_status_reports_the_settings_it_is_running(bound):
    """The page renders these. Served from the engine's own module so it cannot
    describe a configuration the engine is not using."""
    cfg = (await LiveCryptoLoop().status())["config"]
    assert cfg["symbols"] == list(fixed.SYMBOLS)
    assert cfg["starting_balance"] == fixed.STARTING_BALANCE
    assert cfg["daily_loss_limit_pct"] == 5.0
