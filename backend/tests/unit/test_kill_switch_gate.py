"""The armed kill switch must actually block new entries in the live loop.

Regression guard for the silent-safety-failure found in review: arming the kill
switch used to close positions once but had ZERO readers, so the loop kept
opening new trades on the next bar. The loop now consults the kill switch in its
entry gate (LiveCryptoLoop._entry_block_reason).
"""
from __future__ import annotations

import pytest

from app.services.compliance.kill_switch import kill_switch
from app.services.live.crypto_loop import LiveCryptoLoop


@pytest.fixture(autouse=True)
def _disarm_after():
    kill_switch.disarm()
    yield
    kill_switch.disarm()


async def test_entry_allowed_when_idle():
    loop = LiveCryptoLoop()
    assert await loop._entry_block_reason("BTC/USD") is None


async def test_armed_kill_switch_blocks_entry():
    loop = LiveCryptoLoop()
    kill_switch.arm(reason="daily loss limit")
    reason = await loop._entry_block_reason("BTC/USD")
    assert reason is not None
    assert reason.startswith("KILL SWITCH ARMED")
    assert "daily loss limit" in reason


async def test_disarm_reenables_entry():
    loop = LiveCryptoLoop()
    kill_switch.arm(reason="x")
    assert await loop._entry_block_reason("BTC/USD") is not None
    kill_switch.disarm()
    assert await loop._entry_block_reason("BTC/USD") is None


async def test_paused_blocks_entry():
    loop = LiveCryptoLoop()
    loop.paused = True
    assert await loop._entry_block_reason("BTC/USD") == "engine paused"
