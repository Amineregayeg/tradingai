"""Every close path must fire the settle hook, so no close is silently lost.

Regression for the Level-2 finding that kill-switch / manual DELETE closes
settled the broker balance in-memory but never persisted (status() under-reported
and the trade vanished on restart). The loop wires this hook to persistence +
decision resolution; here we prove the broker fires it on ALL close paths.
"""
from __future__ import annotations

from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest
from app.services.broker.paper import PaperBroker


def _order(pair="BTCUSDT", units=1.0, sl=99.0, tp=None):
    return OrderRequest(pair=pair, direction=DirectionType.LONG, order_type=OrderType.MARKET,
                        lot_size=units, price=None, sl=sl, tp=tp)


async def test_settle_hook_fires_on_manual_close():
    events = []
    b = PaperBroker(50_000.0, price_fn=lambda p: 100.0)
    b._on_settle = events.append
    await b.connect()
    res = await b.place_order(_order())
    await b.close_position(res["position_id"])
    assert len(events) == 1
    assert events[0]["pair"] == "BTCUSDT" and events[0]["reason"] == "MANUAL"


async def test_settle_hook_fires_on_close_all():
    events = []
    b = PaperBroker(50_000.0, price_fn=lambda p: 100.0)
    b._on_settle = events.append
    await b.connect()
    for _ in range(3):
        await b.place_order(_order())
    await b.close_all_positions()
    assert len(events) == 3
    assert all(e["reason"] == "CLOSE_ALL" for e in events)


async def test_settle_hook_fires_on_sl_tick():
    events = []
    b = PaperBroker(50_000.0, price_fn=lambda p: 100.0)
    b._on_settle = events.append
    await b.connect()
    await b.place_order(_order(sl=99.0))
    b.on_tick("BTCUSDT", 98.5)  # cross SL
    assert len(events) == 1
    assert events[0]["reason"] == "SL"


def test_loop_wires_the_hook():
    from app.services.live.crypto_loop import LiveCryptoLoop
    loop = LiveCryptoLoop()
    assert loop.paper._on_settle == loop._on_settle_cb
