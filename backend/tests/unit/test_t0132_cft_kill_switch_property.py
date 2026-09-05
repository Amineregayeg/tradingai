"""T-0132 — Malek's ruled kill-switch property, on the venue he actually trades.

> Every position open when the switch was pulled must be reported as CLOSED, FAILED WITH A
> REASON, or NOT ATTEMPTED. A position in none of those three states is a bug by construction.

**WHY THIS OUTRANKED THE MT5 WORK.** The property was proven on MT5 all week and MT5 cannot place
an order — four separate things stop it (`B370`). CFT is the live venue. `B303`'s defect sat on the
adapter Malek trades through: `close_all_positions` caught `BrokerError` **only**, so an
`httpx.ConnectTimeout` — the failure a kill switch is most likely to meet — aborted the loop and
the accumulated results died with the frame. **Zero-closed and four-closed produced identical
output.**

**ON THE SHAPE OF THESE ARMS.** They patch `get_positions` and `close_position` on a real adapter
rather than driving the HTTP transport. That is not the `B368` mistake of letting a hand-built
stand-in replace the producer: **the subject here is the loop's control flow**, and the two
collaborators are its inputs. Where the subject was a producer — the API emitting a blob, the form
emitting a payload — the arm drives the producer instead.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from app.core.exceptions import BrokerError
from app.db.enums import DirectionType
from app.schemas.broker import Position
from app.services.broker.cryptofundtrader import CryptoFundTraderAdapter


def _position(pid: str, pair: str = "BTC/USD") -> Position:
    return Position(
        id=pid, pair=pair, direction=DirectionType.LONG,
        entry_price=Decimal("100"), current_price=Decimal("101"),
        unrealized_pnl=Decimal("1"), lot_size=Decimal("0.5"),
        produced_by="cryptofundtrader", pnl_source="profit",
        duration_seconds=0, open_time=datetime.now(timezone.utc),
    )


def _adapter(positions, close_errors=None, observe_only=False):
    """A real adapter with its two collaborators replaced. `observe_only=False` because
    `_guard_trading` refuses the whole member otherwise, which is a different property."""
    adapter = CryptoFundTraderAdapter(
        email="e", password="p", base_url="https://broker.example.com",
        observe_only=observe_only,
    )
    errors = close_errors or {}
    sent: list[str] = []

    async def _closable():
        """`B376`/`B349`: `close_all_positions` enumerates via `_closable_positions`, NOT via
        `get_positions`, so that a side the adapter cannot read cannot abort the close path.

        **These arms moved with it.** Patching `get_positions` here would leave them driving a
        member the subject no longer calls — green, and measuring nothing. The tuples are what the
        real member returns: an id and a pair, read as strings with no coercion.
        """
        if isinstance(positions, Exception):
            raise positions
        return [(str(p.id or "").strip(), p.pair) for p in positions]

    async def _get_positions():
        if isinstance(positions, Exception):
            raise positions
        return list(positions)

    async def _close(position_id, lot_size=None):
        sent.append(position_id)
        if position_id in errors:
            raise errors[position_id]
        return {"status": "closed", "id": position_id}

    adapter.get_positions = _get_positions          # type: ignore[assignment]
    adapter._closable_positions = _closable         # type: ignore[assignment]
    adapter.close_position = _close                 # type: ignore[assignment]
    return adapter, sent


def test_a_ConnectTimeout_on_one_position_does_NOT_abandon_the_others():
    """**`B303`'s core, and the reason this task outranked MT5.**

    The loop caught `BrokerError` only. `httpx.ConnectTimeout` is an `httpx.RequestError` and not
    a `BrokerError`, so it aborted the loop — positions 3 and 4 were never attempted, and the
    record of positions 1 and 2 died with the frame. **The exception a kill switch is most likely
    to meet was the one the loop could not survive.**
    """
    adapter, sent = _adapter(
        [_position(f"p{i}") for i in range(1, 5)],
        close_errors={"p2": httpx.ConnectTimeout("timed out")},
    )
    report = asyncio.run(adapter.close_all_positions())

    by_id = {r["position_id"]: r for r in report}
    assert set(by_id) == {"p1", "p2", "p3", "p4"}, "positions were abandoned, not reported"
    assert by_id["p2"]["disposition"] == "FAILED"
    assert "ConnectTimeout" in by_id["p2"]["reason"], "failed WITH A REASON, not merely failed"
    assert [by_id[p]["disposition"] for p in ("p1", "p3", "p4")] == ["CLOSED"] * 3
    assert sorted(sent) == ["p1", "p2", "p3", "p4"], "a close was never sent for every position"


def test_an_ABNORMAL_EXIT_still_reports_every_position_and_names_the_in_flight_one():
    """A cancellation is not an `Exception`, so no `except Exception` catches it.

    The rows are built before the loop and published on the adapter, so the record outlives the
    frame — and the row whose close was **already in the air** says so rather than claiming nobody
    reached it (`B337`). `FAILED WITH A REASON` is Malek's vocabulary; the reason clause is where
    *outcome unknown* belongs, which is why there is no fourth disposition.
    """
    adapter, _ = _adapter(
        [_position(f"p{i}") for i in range(1, 5)],
        close_errors={"p2": asyncio.CancelledError()},
    )
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.close_all_positions())

    rows = {r["position_id"]: r for r in exc.value.partial_report}
    assert rows["p1"]["disposition"] == "CLOSED"
    assert rows["p2"]["disposition"] == "FAILED"
    assert "CancelledError" in rows["p2"]["reason"] and "SENT" in rows["p2"]["reason"]
    # The third state must SURVIVE the fix — the row count is 4 under the defect, the fix and the
    # over-fix, so nothing count-based can see this.
    for untouched in ("p3", "p4"):
        assert rows[untouched]["disposition"] == "NOT_ATTEMPTED"
        assert rows[untouched]["reason"] == "the close loop never reached this position"
    assert adapter.last_close_all_report is not None, (
        "the report must also survive on the adapter, for a caller holding no exception"
    )
    assert all("_in_flight" not in r for r in exc.value.partial_report)


def test_it_RAISES_rather_than_reporting_nothing_when_it_cannot_enumerate():
    """Returning `[]` would say *there was nothing to close* — `B292`'s collapse on the kill
    switch's own path, and the one place that sentence is most expensive."""
    adapter, sent = _adapter(httpx.ConnectTimeout("cannot reach the venue"))
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.close_all_positions())
    assert "could not enumerate" in str(exc.value).lower()
    assert "Nothing was attempted" in str(exc.value)
    assert sent == []


def test_positions_without_an_id_get_their_own_rows_and_no_close_is_sent():
    """`B338`. Keying the report on a position id loses a row to a duplicate or an empty string,
    and a report holding fewer rows than there were positions is the ruled property failing
    SILENTLY rather than loudly."""
    adapter, sent = _adapter([_position("p1"), _position(""), _position("")])
    report = asyncio.run(adapter.close_all_positions())

    assert len(report) == 3, f"positions collapsed into {len(report)} row(s)"
    assert sent == ["p1"], "a close was sent for a position with no id"
    unaddressable = [r for r in report if not r["position_id"]]
    assert len(unaddressable) == 2
    for row in unaddressable:
        assert row["disposition"] == "FAILED", "unaddressable must not read as NOT_ATTEMPTED"
        assert "no position id" in row["reason"]


def test_duplicate_ids_still_produce_one_row_each():
    """The must-hit sibling: a collision loses a row exactly as an empty string does."""
    adapter, _ = _adapter([_position("dup"), _position("dup"), _position("p3")])
    report = asyncio.run(adapter.close_all_positions())
    assert len(report) == 3
    assert sorted(r["position_id"] for r in report) == ["dup", "dup", "p3"]


def test_the_disposition_vocabulary_is_the_SAME_OBJECT_on_both_venues():
    """`T-0132` hoisted the three strings to `BrokerAdapter`.

    They were defined on `MetaTrader5Adapter` alone, so bringing CFT to the ruled property meant
    either a second copy or importing one venue's module into another's. **A ruled property that
    lives in one implementation is a property of that implementation** — and two copies of a
    vocabulary drift while the consumer (`kill_switch.py`) reads only strings.
    """
    from app.services.broker.base import BrokerAdapter
    from app.services.broker.mt5 import MetaTrader5Adapter

    for name in ("CLOSED", "FAILED", "NOT_ATTEMPTED"):
        assert getattr(CryptoFundTraderAdapter, name) is getattr(BrokerAdapter, name)
        assert getattr(MetaTrader5Adapter, name) is getattr(BrokerAdapter, name)
