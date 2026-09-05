"""T-0111 / B372 — the aggregate layer could not say *could-not-ask*.

**PROPERTY, registered by review BEFORE these arms existed:** *every connected adapter is accounted
for in every aggregate read — either its positions are included, or it is named as unasked with a
reason. A caller must never be unable to tell a flat book from an unread one.*

Three states produced byte-identical output — a broker that could not be asked, a broker that is
flat, and a second broker absent entirely. The return type is `list[Position]` and **there is no
value in a list that means *one of these brokers could not be asked***.

**THE VOCABULARY IS `close_all_positions`' REPORT, NOT THE ADAPTER'S EXCEPTION.** The adapter
raises; this layer cannot, because the endpoint's contract is *never an error* and three consumers
rest on it. What transfers is the report shape — one row per subject, a disposition, a reason —
**per ADAPTER rather than per position.**
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.exceptions import BrokerError
from app.db.enums import DirectionType
from app.schemas.broker import Position
from app.services.broker.manager import BrokerManager


def _position(pid: str) -> Position:
    return Position(
        id=pid, pair="BTC/USD", direction=DirectionType.LONG,
        entry_price=Decimal("100"), current_price=Decimal("101"),
        unrealized_pnl=Decimal("1"), lot_size=Decimal("0.5"),
        produced_by="paper", pnl_source="profit",
        duration_seconds=0, open_time=datetime.now(timezone.utc),
    )


class _Adapter:
    def __init__(self, name, positions=None, error=None):
        self.broker_name = name
        self._positions = positions or []
        self._error = error

    async def get_positions(self):
        if self._error is not None:
            raise self._error
        return list(self._positions)


def _manager(**adapters) -> BrokerManager:
    m = BrokerManager()
    m._adapters = dict(adapters)          # type: ignore[attr-defined]
    return m


# ======================================================================================
# THE DIFFERENTIAL — three states that used to be one
# ======================================================================================


def _mixed() -> BrokerManager:
    return _manager(
        c1=_Adapter("paper", [_position("a1"), _position("a2")]),
        c2=_Adapter("cryptofundtrader", error=BrokerError("link down", broker="cft")),
    )


def test_an_UNASKED_adapter_is_NAMED_and_not_silently_dropped():
    """**M-1's target, and it asserts ONLY the reporting.**

    Deliberately split from the arm below. Review's orthogonality condition — the same one `B349`
    needed — is that `M-2` (positions dropped) must NOT kill `M-1`'s arm: **one mutation on the
    reporting and one on the reading, and an arm dying under both is measuring one thing twice.**
    An earlier version of this arm asserted the positions too and would have died under both.
    """
    report = asyncio.run(_mixed().get_all_positions_report())

    assert len(report["unasked"]) == 1
    assert report["unasked"][0]["broker"] == "cryptofundtrader"
    assert "link down" in report["unasked"][0]["reason"], "named WITH a reason, not merely named"
    assert report["asked"] == 1 and report["connected"] == 2


def test_the_HEALTHY_positions_still_come_back_IN_FULL():
    """**M-2's target, and it asserts ONLY the reading.**

    The must-miss for the whole fix: naming the unreachable broker is worthless if the price is
    dropping the positions we CAN see. Reporting and reading are separate properties and are
    measured by separate arms.
    """
    report = asyncio.run(_mixed().get_all_positions_report())
    assert [p.id for p in report["positions"]] == ["a1", "a2"]


def test_a_FLAT_broker_and_an_UNREACHABLE_one_are_DISTINGUISHABLE():
    """**The differential the finding was measured as.** Both used to give `['a1','a2']`."""
    healthy = [_position("a1"), _position("a2")]
    flat = _manager(c1=_Adapter("paper", healthy), c2=_Adapter("cft", []))
    down = _manager(c1=_Adapter("paper", healthy),
                    c2=_Adapter("cft", error=BrokerError("down", broker="cft")))
    absent = _manager(c1=_Adapter("paper", healthy))

    flat_r, down_r, absent_r = (asyncio.run(m.get_all_positions_report())
                                for m in (flat, down, absent))

    assert [p.id for p in flat_r["positions"]] == [p.id for p in down_r["positions"]], (
        "the POSITION lists are identical — which is why the list alone cannot carry this"
    )
    assert flat_r["unasked"] == [] and absent_r["unasked"] == []
    assert len(down_r["unasked"]) == 1, "a flat book and an unread one are still the same output"
    assert flat_r["connected"] == 2 and absent_r["connected"] == 1, (
        "flat and absent differ in the DENOMINATOR, which is the third state"
    )


def test_the_bare_list_CONTRACT_is_unchanged_for_its_three_consumers():
    """M-2's control. `get_all_positions` still returns a bare list and still never raises."""
    m = _manager(
        c1=_Adapter("paper", [_position("a1")]),
        c2=_Adapter("cft", error=BrokerError("down", broker="cft")),
    )
    positions = asyncio.run(m.get_all_positions())
    assert [p.id for p in positions] == ["a1"]


def test_the_ALL_HEALTHY_case_reports_nothing_unasked():
    """The control review requires green under every mutation.

    Without it, *name every adapter as unasked* satisfies each arm above.
    """
    m = _manager(c1=_Adapter("paper", [_position("a1")]), c2=_Adapter("cft", [_position("b1")]))
    report = asyncio.run(m.get_all_positions_report())
    assert report["unasked"] == []
    assert sorted(p.id for p in report["positions"]) == ["a1", "b1"]
    assert report["asked"] == 2
