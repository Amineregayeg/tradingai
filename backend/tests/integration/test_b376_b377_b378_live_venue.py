"""B376 / B377 / B378 — three live-money defects on the venue Malek trades, and their couplings.

Written against **review's kill-set, registered before these arms existed**. Every mutation in it
reads zero against the pre-fix code, because today's committed behaviour IS the mutant.

**B376** — everything unrecognised became a LONG. This is `B336` again and worse three ways: MT5
defaulted to SHORT, this defaults to LONG *which agrees with the common case*; MT5's writes refuse
and CFT trades; and `SELL_LIMIT -> LONG` is the MIRROR of MT5's defect rather than a repeat —
`endswith` over-matched, set-membership under-matches. **Both are the absence of a mapping.**

**B377** — `equity` fell back to `balance`. Traced rather than assumed: it reaches the prop-firm
compliance monitor and the dashboard, **not** position sizing (`ExecutionService` is only ever built
with the loop's simulator, `B350`). It matters more for that, not less — a breach closes the account.

**B378** — created by B377's fix. Before it, an unreachable broker gave a WRONG drawdown; after it,
`get_account` raises and the monitor STOPS UPDATING. The surface reads snapshot HISTORY, so a
missing row is indistinguishable from a quiet period. **A wrong number at least moves.**
"""
from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.exceptions import BrokerError
from app.db.enums import ComplianceState, DirectionType
from app.models.prop_firm_profile import PropFirmProfile
from app.models.prop_firm_snapshot import PropFirmSnapshot
from app.services.broker.cryptofundtrader import CryptoFundTraderAdapter

pytestmark = pytest.mark.asyncio


def _adapter() -> CryptoFundTraderAdapter:
    return CryptoFundTraderAdapter(
        email="e", password="p", base_url="https://broker.example.com", observe_only=True,
    )


# ======================================================================================
# B376 — the direction mapping
# ======================================================================================


@pytest.mark.parametrize("side", ["", None, 0, 1, "ASK", "BID", "MARKET", "LIMIT", "SELL_LIMIT"])
async def test_an_UNRECOGNISED_side_RAISES_and_the_message_NAMES_it(side):
    """`M-376-A`. **Assert the raise AND the value named in it, not merely "not LONG".**

    An arm asserting `!= LONG` passes against a raise, a SHORT, and anything else — and the whole
    point is that an unknown becomes a *question*, which means the message must carry what it could
    not map. `SELL_LIMIT` is in this list deliberately: it contains `SELL` and used to become a
    LONG, which is the mirror of `B336`'s `endswith` over-match.
    """
    with pytest.raises(BrokerError) as exc:
        CryptoFundTraderAdapter._side_to_direction(side)
    message = str(exc.value)
    if side in (None, ""):
        assert "NO side and NO type" in message
    else:
        assert repr(side) in message, f"the refusal does not name what it could not map: {message}"


@pytest.mark.parametrize("side,expected", [
    ("SELL", DirectionType.SHORT), ("sell", DirectionType.SHORT),
    ("SHORT", DirectionType.SHORT), ("S", DirectionType.SHORT),
    ("BUY", DirectionType.LONG), ("buy", DirectionType.LONG),
    ("LONG", DirectionType.LONG), ("B", DirectionType.LONG),
])
async def test_the_KNOWN_spellings_still_map(side, expected):
    """The control for `M-376-A` and `M-376-C` — and **deliberately NOT for `M-376-B`**, which
    mutates exactly this.

    Without it, *raise on anything unrecognised* is satisfiable by a function that raises always.
    """
    assert CryptoFundTraderAdapter._side_to_direction(side) is expected


async def test_the_raise_SURFACES_as_an_unasked_adapter_and_not_a_shorter_list():
    """`M-376-C`, and it is the coupling that makes the raise safe.

    `B376`'s raise sits in position normalisation, so it surfaces in `manager.get_all_positions` —
    **the swallow `B372` measured.** Before B372 landed, this fix would have turned a wrongly-LONG
    position into a position that is NOT THERE: better than a wrong direction, and not what the fix
    intends. Now the broker is NAMED as unasked.
    """
    from app.services.broker.manager import BrokerManager

    class _Bad:
        broker_name = "cryptofundtrader"

        async def get_positions(self):
            raise BrokerError("side 'ASK' not recognised", broker="cryptofundtrader")

    m = BrokerManager()
    m._adapters = {"c1": _Bad()}
    report = await m.get_all_positions_report()
    assert report["positions"] == []
    assert len(report["unasked"]) == 1, "a raising adapter became a silently shorter list"
    assert report["unasked"][0]["broker"] == "cryptofundtrader"


# ======================================================================================
# B377 — equity is not balance
# ======================================================================================

#: `M-377-C`. **THE CAPTURED SHAPE, NOT AN INVENTED ONE.** These keys and values mirror
#: `test_cryptofundtrader_adapter.py`'s `BALANCE_RESP`, documented there as reflecting the live API
#: captured during discovery — **and it carries `equity`, which is the evidence that requiring it
#: is safe.** Note `equity != balance`: a fixture where they are equal cannot distinguish the fix.
CAPTURED_ACCOUNT = {
    "balance": "5000.00", "equity": "5012.00", "margin": "0.00",
    "freeMargin": "5000.00", "marginLevel": "0", "profit": "12.00",
    "netProfit": "12.00", "currency": "USD", "currencyPrecision": 2,
}


async def test_equity_is_READ_and_never_substituted_from_balance():
    """`M-377-B`'s control. The values differ, so reading the wrong key is visible."""
    adapter = _adapter()
    account = adapter._account_from_payload(dict(CAPTURED_ACCOUNT))
    assert account.equity == 5012.00
    assert account.balance == 5000.00
    assert account.equity != account.balance, "the fixture cannot distinguish the fix"


async def test_a_payload_with_NO_equity_REFUSES_rather_than_using_balance():
    """`M-377-A`. `equity` and `balance` are not the same quantity: with the key absent, the old
    code asserted open P&L is zero while `unrealized_pl` on the same object said otherwise.

    It feeds `total_loss = initial_balance - account.equity` in the drawdown monitor, and **a
    prop-firm breach closes the account.**
    """
    payload = {k: v for k, v in CAPTURED_ACCOUNT.items() if k != "equity"}
    with pytest.raises(BrokerError) as exc:
        _adapter()._account_from_payload(payload)
    assert "equity" in str(exc.value)


async def test_the_account_PnL_key_is_recorded_like_its_position_sibling():
    """`B377`'s smaller half. `T-0114` gave `Position.pnl_source` its provenance and left the
    ACCOUNT field twelve lines above with a silent `profit` -> `netProfit` fallback — and `B286`
    says those are not the same quantity."""
    account = _adapter()._account_from_payload(dict(CAPTURED_ACCOUNT))
    assert account.unrealized_pl_source == "profit"

    no_profit = {k: v for k, v in CAPTURED_ACCOUNT.items() if k != "profit"}
    assert _adapter()._account_from_payload(no_profit).unrealized_pl_source == "netProfit"


# ======================================================================================
# B378 — the compliance surface, not the return value
# ======================================================================================


async def _profile(db, account_id="acct-1"):
    profile = PropFirmProfile(
        user_id="system", firm_name="CFT", account_id=account_id, active=True,
        rules_json={"initial_balance": 5000.0, "max_total_loss_pct": 10.0},
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def test_an_UNREACHABLE_broker_RECORDS_not_evaluated_on_the_COMPLIANCE_SURFACE(db_session):
    """`M-378-B`, **the one that matters, and the one my first fix failed.**

    That version built an `unavailable` list, logged at ERROR and returned it — and review's line
    is the row to get right: *an arm asserting the function returns `unavailable` would PASS while
    the monitor still lies.* The surface reads snapshot HISTORY, so the information has to reach a
    ROW. **That was `B366`'s exact shape, sitting inside the fix for a defect described to me as
    `B366`'s shape.**

    So this asserts the SNAPSHOT the surface reads — not the return value.
    """
    from app.services.broker import observe_sync
    from app.services.broker.manager import broker_manager

    profile = await _profile(db_session)

    class _Unreachable:
        broker_name = "cryptofundtrader"
        _account_id = profile.account_id

        async def get_account(self):
            raise httpx.ConnectTimeout("cannot reach the venue")

    original = dict(broker_manager._adapters)
    broker_manager._adapters = {"c1": _Unreachable()}
    try:
        result = await observe_sync.sync_all_observe_only(db_session, "system")
    finally:
        broker_manager._adapters = original

    rows = (await db_session.execute(select(PropFirmSnapshot))).scalars().all()
    assert len(rows) == 1, "nothing reached the surface — the monitor still shows the last value"
    assert rows[0].state is ComplianceState.UNAVAILABLE
    assert rows[0].equity is None and rows[0].total_loss is None, (
        "an UNAVAILABLE row must carry NO figures — writing the last known values in IS the "
        "defect, and zeros would manufacture a drawdown on the number a breach is computed from"
    )
    assert result["synced"] == 0 and len(result["unavailable"]) == 1


async def test_a_HEALTHY_account_still_records_a_real_evaluation(db_session):
    """The control for `M-378-A`/`M-378-B`: a fix that records UNAVAILABLE for everything would
    satisfy the arm above and destroy the monitor."""
    from app.services.broker import observe_sync
    from app.services.broker.manager import broker_manager
    from app.services.broker.base import Account

    profile = await _profile(db_session, account_id="acct-2")

    class _Healthy:
        broker_name = "cryptofundtrader"
        _account_id = profile.account_id

        async def get_account(self):
            return Account(account_id="acct-2", broker="cryptofundtrader",
                           balance=5000.0, equity=5012.0, currency="USD",
                           unrealized_pl=12.0, unrealized_pl_source="profit")

    original = dict(broker_manager._adapters)
    broker_manager._adapters = {"c1": _Healthy()}
    try:
        result = await observe_sync.sync_all_observe_only(db_session, "system")
    finally:
        broker_manager._adapters = original

    rows = (await db_session.execute(select(PropFirmSnapshot))).scalars().all()
    assert len(rows) == 1
    assert rows[0].state is not ComplianceState.UNAVAILABLE
    assert rows[0].equity is not None
    assert result["synced"] == 1 and result["unavailable"] == []


async def test_the_sync_returns_a_REPORT_and_not_a_count(db_session):
    """`M-378-C`. The caller in `main.py` did `count = await ...; if count:` — and **a non-empty
    dict is always truthy**, so it logged every pass and reported `profiles={'synced': 0, ...}` as
    though it were a number. `if count:` used to mean *something synced*.

    This pins the contract the caller now depends on: both keys, always present, whatever happened.
    """
    from app.services.broker import observe_sync
    from app.services.broker.manager import broker_manager

    original = dict(broker_manager._adapters)
    broker_manager._adapters = {}
    try:
        result = await observe_sync.sync_all_observe_only(db_session, "system")
    finally:
        broker_manager._adapters = original

    assert isinstance(result, dict), "the caller reads result['synced']; an int breaks it"
    assert result == {"synced": 0, "unavailable": []}
