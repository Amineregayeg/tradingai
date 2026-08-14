"""The shadow must evaluate a bar the ICT path was not free to trade.

WHY THIS IS THE WHOLE TASK
`_shadow_evaluate` used to sit BELOW the entry-gate `return`, so the contract engine
never saw a bar where the ICT path was blocked — and `already in a position` is the
engine's normal state. It therefore missed **exactly the bars following an entry**,
which are the bars on which the two strategies would most differ (KNOWN_ISSUES B34).

On 2026-08-13 that was an entry at 19:00 and then 20:00, 21:00, 22:00 all skipped:
three consecutive bars the contract engine never evaluated.

THE ASSERTION IS PRESENCE ON A SKIPPED BAR, NOT A COUNT. A count rises when volume
rises and would pass on the 5m switch alone. What has to be true is that a bar the
engine *declined to trade* still produced a contract verdict.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services.live.crypto_loop import LiveCryptoLoop

T0 = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _bars(n: int = 80) -> pd.DataFrame:
    idx = pd.DatetimeIndex([T0 + timedelta(minutes=5 * i) for i in range(n)], tz="UTC")
    base = [100.0 + i for i in range(n)]
    return pd.DataFrame({"open": base, "high": [b + 1 for b in base],
                         "low": [b - 1 for b in base], "close": [b + 0.5 for b in base],
                         "volume": [1.0] * n}, index=idx)


@pytest.fixture
def loop_with_a_blocked_entry(monkeypatch):
    """A loop whose entry gate refuses — the engine's normal state while holding."""
    loop = LiveCryptoLoop()
    seen: list[str] = []
    acted: list[tuple[str, str]] = []

    async def _fetch(*a, **k):
        return _bars()

    async def _blocked(pair):
        return "already in a position"

    async def _shadow(pair, entry, engine_policy=None):
        seen.append(pair)

    async def _act(kind, msg):
        acted.append((kind, msg))

    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_entry_block_reason", _blocked)
    monkeypatch.setattr(loop, "_shadow_evaluate", _shadow)
    monkeypatch.setattr(loop, "_act", _act)
    return loop, seen, acted


@pytest.mark.asyncio
async def test_a_bar_the_engine_skipped_still_reaches_the_shadow(loop_with_a_blocked_entry):
    """THE CRITERION. Blocked entry, and the contract engine must still evaluate."""
    loop, seen, acted = loop_with_a_blocked_entry
    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert seen == ["BTC/USD"], (
        "the entry gate blocked and the shadow never ran — the contract engine is "
        "blind on exactly the bars where the two strategies differ most"
    )
    assert any(k == "skip" for k, _ in acted), "the engine should still have skipped"


@pytest.mark.asyncio
async def test_the_shadow_runs_before_the_gate_not_merely_somewhere(monkeypatch):
    """Ordering, asserted directly, so a later refactor cannot quietly re-sink it.

    A test that only checks "the shadow ran" passes if someone moves the call back
    below the gate and the gate happens to be open. This pins the sequence.

    T-0011 CHANGED THE EXPECTED SEQUENCE AND NOT THE PROPERTY. `_entry_block_reason` is
    now called a SECOND time, before the shadow, purely to put "what the live engine
    would have done with this bar" into the shadow's record — the gate below still
    re-evaluates and is still the only call that decides anything.

    The property T-0010 pinned is intact and is still what fails here: if the shadow is
    sunk back below the gate, this gate BLOCKS and returns, so "shadow" disappears from
    the list entirely rather than merely moving. The sequence is asserted exactly rather
    than by `in`, because that also pins T-0011's own requirement — TWO gate calls, not
    one. A single call would mean the early value was reused at the gate, which is a
    trading behaviour change (a position closed during the shadow's `await` would be
    skipped on a reason that is no longer true).
    """
    loop = LiveCryptoLoop()
    order: list[str] = []

    async def _fetch(*a, **k):
        return _bars()

    async def _blocked(pair):
        order.append("gate")
        return "already in a position"

    async def _shadow(pair, entry, engine_policy=None):
        order.append("shadow")

    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_entry_block_reason", _blocked)
    monkeypatch.setattr(loop, "_shadow_evaluate", _shadow)
    monkeypatch.setattr(loop, "_act", lambda *a, **k: _noop())

    await loop._tick_symbol("BTC/USD", "BTCUSDT")
    assert order == ["gate", "shadow", "gate"], (
        f"the shadow must run between the record-only read and the deciding gate, and "
        f"the gate must re-evaluate rather than reuse; got {order}"
    )


async def _noop():
    return None
