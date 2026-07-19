"""Unit tests for the paper broker + execution service (the execution path)."""
from __future__ import annotations

from app.db.enums import DirectionType, OrderType
from app.services.broker.paper import PaperBroker
from app.services.execution.service import (
    ExecMode,
    ExecutionService,
    Signal,
    size_position,
)


def test_size_position_from_risk():
    # 1% of 50k = 500 risk; stop distance 600 -> 0.8333 units
    units = size_position(50_000, 0.01, entry=60_000, sl=59_400)
    assert round(units, 4) == round(500 / 600, 4)


def test_size_position_zero_stop_is_zero():
    assert size_position(50_000, 0.01, entry=100, sl=100) == 0.0


async def test_paper_long_hits_tp_realizes_2r():
    b = PaperBroker(50_000.0, price_fn=lambda p: 60_000.0)
    await b.connect()
    ex = ExecutionService(b, ExecMode.PAPER)
    # entry 60000, sl 59400 (1R=600), tp 61200 (2R)
    sig = Signal("BTCUSDT", DirectionType.LONG, entry=60_000, sl=59_400, tp=61_200,
                 risk_pct=0.01, order_type=OrderType.MARKET, approved=True)
    res = await ex.execute(sig)
    assert res["status"] == "FILLED"
    assert (await b.get_account()).open_trade_count == 1
    evs = b.on_tick("BTCUSDT", 61_250)            # cross TP
    assert evs and evs[0]["reason"] == "TP"
    acct = await b.get_account()
    assert round(acct.balance - 50_000) == 1_000   # 2R on 1% risk = +2% = +$1000
    assert acct.open_trade_count == 0


async def test_paper_short_hits_sl_realizes_minus_1r():
    b = PaperBroker(50_000.0, price_fn=lambda p: 60_000.0)
    await b.connect()
    ex = ExecutionService(b, ExecMode.PAPER)
    sig = Signal("BTCUSDT", DirectionType.SHORT, entry=60_000, sl=60_600, tp=58_800,
                 risk_pct=0.01, order_type=OrderType.MARKET, approved=True)
    await ex.execute(sig)
    evs = b.on_tick("BTCUSDT", 60_650)            # cross SL (short)
    assert evs and evs[0]["reason"] == "SL"
    assert round((await b.get_account()).balance - 50_000) == -500  # -1R = -1% = -$500


def test_no_live_execmode_exists():
    # The real-money execution path was removed. There must be no LIVE member.
    assert not hasattr(ExecMode, "LIVE")
    assert {m.name for m in ExecMode} == {"OBSERVE", "PAPER"}


async def test_execute_rejects_non_simulation_broker():
    # A broker that is not a simulation must never be executable here.
    class FakeLiveBroker:
        is_simulation = False

        async def get_account(self):  # pragma: no cover - should never be reached
            raise AssertionError("get_account must not be called on a live broker")

    ex = ExecutionService(FakeLiveBroker(), ExecMode.PAPER)
    sig = Signal("BTCUSDT", DirectionType.LONG, entry=60_000, sl=59_400, tp=61_200)
    try:
        await ex.execute(sig)
        raise AssertionError("expected RuntimeError for non-simulation broker")
    except RuntimeError as exc:
        assert "simulation" in str(exc)


async def test_observe_mode_sizes_but_never_places():
    b = PaperBroker(50_000.0, price_fn=lambda p: 60_000.0)
    await b.connect()
    ex = ExecutionService(b, ExecMode.OBSERVE)
    sig = Signal("BTCUSDT", DirectionType.LONG, entry=60_000, sl=59_400, tp=61_200)
    res = await ex.execute(sig)
    assert res["status"] == "observed" and res["would_size"] > 0
    assert (await b.get_account()).open_trade_count == 0


async def test_close_all_positions():
    b = PaperBroker(50_000.0, price_fn=lambda p: 100.0)
    await b.connect()
    ex = ExecutionService(b, ExecMode.PAPER)
    for _ in range(3):
        await ex.execute(Signal("X", DirectionType.LONG, 100, 99, 102, approved=True))
    assert (await b.get_account()).open_trade_count == 3
    closed = await b.close_all_positions()
    assert len(closed) == 3
    assert (await b.get_account()).open_trade_count == 0
