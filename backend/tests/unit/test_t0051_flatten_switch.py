"""T-0051 — GATE-022's 19:00 flatten gated OFF, so the engine can be STARTED.

**Malek's operating decision, 2026-08-19.** Starting the engine as it stood would apply an
unratified default to a live paper balance: the 19:00 flatten is Salim's for the EURUSD / algo HT
v2.0 strand, and whether a 24/7 instrument flattens daily is his **question 4, unanswered**.

    GATED   the ORDER
    NOT     the rule, its verdict, its record, its 19:00 boundary, or its registry entry

> **ARM 2 IS THE ONE THAT MATTERS.** *A gate defaulting off is trivially satisfiable by deleting
> the feature* — `B172`'s lesson that the artefact built to prove a thing works can be
> uninformative about it. If the flatten cannot be made to fire, the capability was removed rather
> than gated, and every arm below would still be green.

**AND THE CONSEQUENCE IS ARMED, NOT JUST NOTED:** `T-0050` built `SESSION_CLOSE` because the 30%
runner has no final target. With this off, a runner terminates on `STOP_HIT` alone.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest
from app.services.broker.paper import PaperBroker
from app.services.live import crypto_loop as loop_mod
from app.services.rules.exit_001_v1_model import (
    DECLARED_SESSION_CLOSE, DECLARED_SESSION_FLATTEN, SessionClose,
)

NY = ZoneInfo("America/New_York")
AT_1900 = datetime(2026, 8, 19, 19, 0, tzinfo=NY)


class _Loop:
    def __init__(self, broker: PaperBroker) -> None:
        self.paper = broker
        self._tranche_plans: dict[str, dict] = {}
        self._partialled: set[str] = set()
        self._last_session_close: date | None = None
        self.acts: list[tuple[str, str]] = []

    async def _act(self, kind: str, message: str) -> None:
        self.acts.append((kind, message))

    _close_at_session_end = loop_mod.LiveCryptoLoop._close_at_session_end


@pytest.fixture(autouse=True)
def _silence_ws(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(loop_mod.ws_manager, "push_position_close", _noop)


async def _open_position(broker: PaperBroker) -> str:
    broker._marks["BTC/USDT"] = 100.0
    res = await broker.place_order(OrderRequest(
        pair="BTC/USDT", direction=DirectionType.LONG, order_type=OrderType.MARKET,
        lot_size=10.0, sl=95.0, tp=None,
    ))
    return res["position_id"]


# ---------------------------------------------------------------------------
# ARM 1 — the default: 19:00 with an open position places NO order
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ARM1_with_the_flag_OFF_no_close_order_is_placed_at_1900():
    """**Asserted on the ORDER, not the verdict.** A verdict-level assertion would pass even if
    the flatten still fired, because GATE-022 reaches FAIL either way."""
    assert DECLARED_SESSION_FLATTEN.enabled is False, "the default must be OFF"

    broker = PaperBroker(starting_balance=10_000.0)
    await _open_position(broker)
    loop = _Loop(broker)

    await loop._close_at_session_end(AT_1900)

    still_open = await broker.get_positions()
    assert len(still_open) == 1, (
        "a position was closed at 19:00 while the flatten flag is OFF — the suppression is not "
        "reaching the order path"
    )
    assert float(still_open[0].lot_size) == 10.0


# ---------------------------------------------------------------------------
# ARM 2 — THE ONE THAT MATTERS: the capability still exists
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ARM2_with_the_flag_ON_the_SAME_fixture_DOES_flatten(monkeypatch):
    """**If this cannot fire, the flag removed the capability instead of gating it — and ARM 1,
    ARM 3 and every other test in this file would still be green.**

    The same fixture as ARM 1, differing only in the flag. *Anything else differing between the
    two would make the pair uninformative about the flag*, which is the whole point of a control.
    """
    monkeypatch.setattr(
        loop_mod, "DECLARED_SESSION_FLATTEN", replace(DECLARED_SESSION_FLATTEN, enabled=True)
    )

    broker = PaperBroker(starting_balance=10_000.0)
    await _open_position(broker)
    loop = _Loop(broker)

    await loop._close_at_session_end(AT_1900)

    assert await broker.get_positions() == [], (
        "the flatten did NOT fire with the flag ON — T-0051 deleted GATE-022's capability rather "
        "than gating it, and every other arm in this file is uninformative about that"
    )
    assert any("SESSION_CLOSE" in msg for _kind, msg in loop.acts)


# ---------------------------------------------------------------------------
# ARM 3 — the verdict is recorded either way
# ---------------------------------------------------------------------------
def test_ARM3_gate_022_still_evaluates_and_still_reaches_its_verdict():
    """A flag that suppresses the RECORD as well as the action destroys the evidence Salim's
    answer will be applied to — how often a runner WOULD have been cut, and at what R."""
    assert SessionClose.evaluate(AT_1900).verdict == "FAIL"
    assert SessionClose.evaluate(AT_1900.replace(hour=18, minute=59)).verdict == "PASS"
    assert SessionClose.evaluate().verdict == "NOT_APPLICABLE"

    values = SessionClose.evaluate(AT_1900).values
    assert values["session_close_ny"] == "19:00"
    assert values["session_closed"] is True


@pytest.mark.asyncio
async def test_ARM3b_the_suppressed_path_REPORTS_WHAT_WOULD_HAVE_CLOSED():
    """**`0 flattens` must never read as "it ran and found nothing".**

    `B179`'s trap is being built here deliberately — an inert-but-correct component whose null
    output is indistinguishable from a working one — so the count of what WOULD have closed is
    the load-bearing half of the record, not a nicety.
    """
    broker = PaperBroker(starting_balance=10_000.0)
    await _open_position(broker)
    loop = _Loop(broker)

    await loop._close_at_session_end(AT_1900)

    suppressed = [m for _k, m in loop.acts if "SUPPRESSED" in m]
    assert suppressed, "the suppression produced no record at all — it is silently inert"
    message = suppressed[0]
    assert "1 position(s) WOULD have been flattened" in message, (
        "the record does not say WHAT WOULD HAVE CLOSED — without it, suppressed and idle are "
        "the same line"
    )
    assert "question 4" in message and "STOP_HIT only" in message


# ---------------------------------------------------------------------------
# The flag is OURS, and its retirement is a CONDITION
# ---------------------------------------------------------------------------
def test_the_flag_is_ENGINEERING_and_retires_on_a_CONDITION_not_a_date():
    """**The flag must not become the answer.** A default that outlives the question it was
    waiting on has silently become doctrine — which is `GATE-014`'s shape and this loop's most
    repeated failure."""
    assert DECLARED_SESSION_FLATTEN.ratified is False
    assert "[ENGINEERING]" in DECLARED_SESSION_FLATTEN.authority
    assert "Malek" in DECLARED_SESSION_FLATTEN.source
    condition = DECLARED_SESSION_FLATTEN.retirement_condition
    assert "CONDITION, NOT A DATE" in condition
    assert "DELETED" in condition, (
        "the retirement says the flag is disabled rather than DELETED — a flag left in place "
        "after the ruling is a second statement of the doctrine, which is GATE-011's defect"
    )
    # The rule it gates is untouched: still HIS, still ratified where he ruled it.
    assert DECLARED_SESSION_CLOSE.local_time == time(19, 0)


def test_the_OFF_state_is_visible_on_the_status_payload_without_reading_source():
    """`B179`: whoever asks "did the daily flatten run?" must be able to tell SUPPRESSED from
    IDLE from WORKING. The switch and its authority ride on `/api/engine/status`."""
    exposed = DECLARED_SESSION_FLATTEN.as_values()
    assert exposed["session_flatten_enabled"] is False
    assert exposed["session_flatten_enabled_ratified"] is False
    assert "[ENGINEERING]" in exposed["session_flatten_enabled_authority"]
    assert "retirement_condition" in " ".join(exposed)


def test_GATE_022_is_still_IMPLEMENTED_and_still_claims_its_id():
    """DO NOT remove the rule, its module, its tests or its registry entry. Gating an action is
    not withdrawing a rule, and the coverage report must not move."""
    import app.services.rules as rules_pkg
    from app.services.telemetry import contract_loader as contract

    assert "GATE-022" in rules_pkg.implemented_ids()
    assert contract.rule("GATE-022")["status"] == "READY"
    assert SessionClose.RULE_ID == "GATE-022"
