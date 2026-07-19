"""Tests for the local CryptoFundTrader prop-firm simulator (CONTRACT 7d).

``SimPropFirmBroker`` is a local, in-process simulator of a prop-firm challenge
account. CryptoFundTrader exposes no real demo/sandbox host, so "prop firm in
simulation mode" is implemented as this simulator, which (a) enforces the prop-firm
rules and (b) is *structurally incapable* of a real order — it imports no HTTP client
and opens no socket; market prices arrive only through an injected read-only async
``price_source``.

These tests verify:
  * a daily-loss breach halts the account (status -> "failed");
  * a max-drawdown breach halts the account (status -> "failed");
  * reaching the profit target passes the account (status -> "passed");
  * the pre-trade rule engine refuses an order whose worst case would breach a limit;
  * ``is_simulation`` is True;
  * the source file imports NO httpx / requests / aiohttp (real-order impossibility).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest
from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MutablePrice:
    """A controllable read-only async price source.

    The injected ``price_source`` callable the simulator awaits — mutate ``.px``
    between opening and closing a position to control the realized PnL.
    """

    def __init__(self, px: float) -> None:
        self.px = float(px)

    async def __call__(self, pair: str) -> float:
        return self.px


def _long(pair: str = "BTCUSDT", units: float = 1000.0, sl=None, tp=None) -> OrderRequest:
    return OrderRequest(
        pair=pair,
        direction=DirectionType.LONG,
        order_type=OrderType.MARKET,
        lot_size=units,
        price=None,
        sl=sl,
        tp=tp,
    )


# ---------------------------------------------------------------------------
# is_simulation + rule_state shape
# ---------------------------------------------------------------------------


def test_is_simulation_is_true():
    sim = SimPropFirmBroker(PropFirmRules(), _MutablePrice(100.0))
    assert sim.is_simulation is True


def test_rule_state_reports_full_contract_shape():
    sim = SimPropFirmBroker(
        PropFirmRules(
            starting_balance=50_000.0,
            daily_loss_limit_pct=5.0,
            max_drawdown_pct=10.0,
            profit_target_pct=10.0,
            min_trading_days=5,
        ),
        _MutablePrice(100.0),
    )
    st = sim.rule_state()
    expected_keys = {
        "starting_balance",
        "balance",
        "equity",
        "day_pnl_pct",
        "drawdown_pct",
        "profit_target_pct",
        "daily_loss_limit_pct",
        "max_drawdown_pct",
        "trading_days",
        "min_trading_days",
        "halted",
        "breach_reason",
        "status",
    }
    assert expected_keys <= set(st)
    # Fresh account: active, not halted, seeded from the round constant.
    assert st["status"] == "active"
    assert st["halted"] is False
    assert st["breach_reason"] is None
    assert st["starting_balance"] == 50_000.0
    assert st["balance"] == 50_000.0


# ---------------------------------------------------------------------------
# Daily-loss breach -> halt / failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_loss_breach_halts_account():
    price = _MutablePrice(100.0)
    # 5% daily loss limit (= $2,500); huge max-drawdown so the DAILY limit is the
    # only thing that can trip on this trade.
    rules = PropFirmRules(
        starting_balance=50_000.0,
        daily_loss_limit_pct=5.0,
        max_drawdown_pct=50.0,
        profit_target_pct=10.0,
        min_trading_days=0,
    )
    sim = SimPropFirmBroker(rules, price)

    resp = await sim.place_order(_long(units=1000.0))
    assert resp["status"] == "FILLED"
    pid = resp["position_id"]

    # Move price down 5 -> realized loss of $5,000 (10% of balance) on close.
    price.px = 95.0
    ev = await sim.close_position(pid)
    assert ev["pnl"] < 0

    st = sim.rule_state()
    assert st["halted"] is True
    assert st["status"] == "failed"
    assert st["breach_reason"] == "daily_loss_limit"
    assert st["day_pnl_pct"] < 0

    # A halted account refuses every new order.
    resp2 = await sim.place_order(_long(units=10.0))
    assert resp2["status"] == "REJECTED"
    assert len(await sim.get_positions()) == 0


# ---------------------------------------------------------------------------
# Max-drawdown breach -> halt / failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_drawdown_breach_halts_account():
    price = _MutablePrice(100.0)
    # Daily-loss limit set very wide (90%) so a 20% loss can NOT be the daily cause;
    # the only limit a 20% loss can breach is the 8% trailing max-drawdown.
    rules = PropFirmRules(
        starting_balance=50_000.0,
        daily_loss_limit_pct=90.0,
        max_drawdown_pct=8.0,
        profit_target_pct=50.0,
        min_trading_days=0,
    )
    sim = SimPropFirmBroker(rules, price)

    resp = await sim.place_order(_long(units=1000.0))
    assert resp["status"] == "FILLED"
    pid = resp["position_id"]

    # Move price down 10 -> realized loss of $10,000 = 20% drawdown from peak.
    price.px = 90.0
    await sim.close_position(pid)

    st = sim.rule_state()
    assert st["halted"] is True
    assert st["status"] == "failed"
    # Isolated by construction: a 20% loss is below the 90% daily limit, so the halt
    # must be the trailing max-drawdown, not the daily loss.
    assert st["breach_reason"] == "max_drawdown"
    assert st["drawdown_pct"] >= rules.max_drawdown_pct


# ---------------------------------------------------------------------------
# Profit target -> passed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profit_target_marks_account_passed():
    price = _MutablePrice(100.0)
    rules = PropFirmRules(
        starting_balance=50_000.0,
        daily_loss_limit_pct=5.0,
        max_drawdown_pct=10.0,
        profit_target_pct=10.0,  # target equity = $55,000
        min_trading_days=1,
    )
    sim = SimPropFirmBroker(rules, price)

    resp = await sim.place_order(_long(units=1000.0))
    assert resp["status"] == "FILLED"
    pid = resp["position_id"]

    # Move price up 6 -> realized gain of $6,000 (12%) > 10% profit target.
    price.px = 106.0
    ev = await sim.close_position(pid)
    assert ev["pnl"] > 0

    st = sim.rule_state()
    assert st["status"] == "passed"
    assert st["halted"] is True
    assert st["breach_reason"] is None
    assert st["trading_days"] >= 1

    # Passed account is halted: it accepts no further orders.
    resp2 = await sim.place_order(_long(units=10.0))
    assert resp2["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Pre-trade refusal: an order whose worst case would breach is rejected up front
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pretrade_refuses_order_that_could_breach_daily_loss():
    price = _MutablePrice(100.0)
    rules = PropFirmRules(
        starting_balance=50_000.0,
        daily_loss_limit_pct=5.0,  # = $2,500
        max_drawdown_pct=50.0,
        profit_target_pct=10.0,
        min_trading_days=0,
    )
    sim = SimPropFirmBroker(rules, price)

    # Worst case (stop at 90 on 1,000 units) = $10,000 loss > $2,500 daily limit.
    resp = await sim.place_order(_long(units=1000.0, sl=90.0))
    assert resp["status"] == "REJECTED"
    assert resp["reason"] == "would_breach_daily_loss"

    # A pre-trade refusal does NOT open a position and does NOT halt the account.
    assert len(await sim.get_positions()) == 0
    st = sim.rule_state()
    assert st["halted"] is False
    assert st["status"] == "active"


# ---------------------------------------------------------------------------
# Day boundary: the daily-loss guard must measure THIS day's realized pnl
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_day_resets_daily_loss_guard():
    """A fresh calendar day must not be judged against yesterday's realized loss.

    Regression for the ordering bug where the daily-loss pre-trade guard read
    _day_pnl BEFORE _roll_day ran, so on a new day it evaluated against the
    previous day's accumulated loss and wrongly refused valid orders.
    """
    from datetime import date, timedelta

    price = _MutablePrice(100.0)
    rules = PropFirmRules(
        starting_balance=50_000.0,
        daily_loss_limit_pct=5.0,  # = $2,500
        max_drawdown_pct=50.0,
        profit_target_pct=10.0,
        min_trading_days=0,
    )
    sim = SimPropFirmBroker(rules, price)

    # Simulate YESTERDAY having accumulated a near-limit loss.
    sim._current_day = date.today() - timedelta(days=1)
    sim._day_pnl = -2_400.0  # just under the $2,500 daily limit, yesterday

    # A modest order TODAY (worst case $1,000) must FILL: the day rolls and
    # _day_pnl resets to 0 before the guard runs. With the old ordering the guard
    # saw (-2,400 - 1,000) = -3,400 <= -2,500 and wrongly rejected.
    resp = await sim.place_order(_long(units=1000.0, sl=99.0))
    assert resp["status"] == "FILLED"
    assert sim._day_pnl == 0.0  # rolled over to the new day


# ---------------------------------------------------------------------------
# Structural real-order impossibility: no network client imports
# ---------------------------------------------------------------------------


def test_source_imports_no_network_client():
    """The simulator must import no httpx / requests / aiohttp (and never pull one
    into its module namespace) — it is structurally incapable of a real order."""
    import app.services.broker.cft_sim as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    offending = re.search(
        r"^\s*(?:import|from)\s+(?:httpx|requests|aiohttp)\b",
        source,
        re.MULTILINE,
    )
    assert offending is None, f"cft_sim must not import a network client: {offending!r}"

    for name in ("httpx", "requests", "aiohttp"):
        assert not hasattr(mod, name), f"cft_sim must not bind {name} in its namespace"
