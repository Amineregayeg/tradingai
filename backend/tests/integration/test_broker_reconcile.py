"""Broker connections must recover on their own (task 4.3, closes KNOWN_ISSUES B4).

THE DEFECT THIS PINS
`connected` in the database is the DESIRED state — "the user wants this live".
`load_from_db` used to overwrite it with False whenever a startup connect
failed, which is also exactly what a deliberate disconnect writes. Once the two
were indistinguishable, nothing could tell "the user turned this off" from "this
broke", so nothing retried.

That turned a timing race into a silent, indefinite outage. Measured: the api is
ready ~1.4s after start; the cft-bridge needs ~2 min (pip install + Chromium).
On a host reboot the api asks before the bridge can answer, failed once, erased
the intent, and never tried again — and the dashboard showed *no broker at all*
rather than an error, so nobody would notice until they went looking.

`depends_on` cannot fix this: the bridge is a separate compose project by
design, so Docker cannot order them.
"""
from __future__ import annotations

import json
from decimal import Decimal  # noqa: F401 - kept for parity with sibling tests

import pytest

from app.core.security import encrypt_credentials
from app.models.broker_connection import BrokerConnection
from app.services.broker import broker_manager

pytestmark = pytest.mark.asyncio


class FakeAdapter:
    broker_name = "cryptofundtrader"
    observe_only = True
    is_simulation = False

    def __init__(self, **_):
        self.connected = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False


def _row(connected: bool = True) -> BrokerConnection:
    return BrokerConnection(
        user_id="system",
        broker="cryptofundtrader",
        encrypted_creds=encrypt_credentials(json.dumps({"email": "e", "password": "p"})),
        account_id="",
        environment="live",
        connected=connected,
    )


@pytest.fixture
def clean_manager():
    original = dict(broker_manager._adapters)          # noqa: SLF001
    broker_manager._adapters.clear()                   # noqa: SLF001
    broker_manager._reconnect_failures.clear()         # noqa: SLF001
    broker_manager._reconnect_ticks = 0                # noqa: SLF001
    yield
    broker_manager._adapters.clear()                   # noqa: SLF001
    broker_manager._adapters.update(original)          # noqa: SLF001


# ---------------------------------------------------------------------------
# The core recovery property
# ---------------------------------------------------------------------------
async def test_a_connection_with_no_adapter_is_recovered(
    clean_manager, db_session, monkeypatch
):
    """The exact reboot scenario: intent recorded, adapter missing."""
    monkeypatch.setattr(
        "app.services.broker.manager._make_adapter", lambda **kw: FakeAdapter()
    )
    row = _row(connected=True)
    db_session.add(row)
    await db_session.commit()

    assert str(row.id) not in broker_manager._adapters  # noqa: SLF001

    result = await broker_manager.reconcile_connections(db_session)

    assert result["recovered"] == 1
    assert str(row.id) in broker_manager._adapters, "the connection was not restored"  # noqa: SLF001


async def test_startup_failure_does_not_erase_the_users_intent(
    clean_manager, db_session, monkeypatch
):
    """The root-cause regression.

    A failed startup connect must leave connected=True, or the supervisor has
    nothing to act on and the outage becomes permanent.
    """
    def boom(**_):
        raise RuntimeError("cft-bridge is still booting")

    monkeypatch.setattr("app.services.broker.manager._make_adapter", boom)
    row = _row(connected=True)
    db_session.add(row)
    await db_session.commit()

    await broker_manager.load_from_db(db_session)
    await db_session.refresh(row)

    assert row.connected is True, (
        "a transient startup failure erased the user's intent; nothing will retry"
    )


async def test_recovery_after_a_failed_startup(clean_manager, db_session, monkeypatch):
    """End to end: fail at startup like a cold bridge, then succeed on retry."""
    state = {"up": False}

    def maybe(**_):
        if not state["up"]:
            raise RuntimeError("bridge not ready")
        return FakeAdapter()

    monkeypatch.setattr("app.services.broker.manager._make_adapter", maybe)
    row = _row(connected=True)
    db_session.add(row)
    await db_session.commit()

    await broker_manager.load_from_db(db_session)
    assert str(row.id) not in broker_manager._adapters  # noqa: SLF001

    state["up"] = True                       # the bridge finishes booting
    result = await broker_manager.reconcile_connections(db_session)

    assert result["recovered"] == 1
    assert str(row.id) in broker_manager._adapters  # noqa: SLF001


# ---------------------------------------------------------------------------
# It must not overreach
# ---------------------------------------------------------------------------
async def test_a_deliberately_disconnected_connection_is_left_alone(
    clean_manager, db_session, monkeypatch
):
    """connected=False means the user turned it off. Reconnecting it would
    override a deliberate decision — the mirror image of the original bug."""
    monkeypatch.setattr(
        "app.services.broker.manager._make_adapter", lambda **kw: FakeAdapter()
    )
    row = _row(connected=False)
    db_session.add(row)
    await db_session.commit()

    result = await broker_manager.reconcile_connections(db_session)

    assert result["recovered"] == 0
    assert str(row.id) not in broker_manager._adapters  # noqa: SLF001


async def test_a_healthy_connection_is_not_reconnected(
    clean_manager, db_session, monkeypatch
):
    """Reconnecting a live session would cost an ~11s browser login for nothing."""
    made = {"n": 0}

    def counting(**_):
        made["n"] += 1
        return FakeAdapter()

    monkeypatch.setattr("app.services.broker.manager._make_adapter", counting)
    row = _row(connected=True)
    db_session.add(row)
    await db_session.commit()

    await broker_manager.reconcile_connections(db_session)
    await broker_manager.reconcile_connections(db_session)
    await broker_manager.reconcile_connections(db_session)

    assert made["n"] == 1, "a healthy connection was needlessly rebuilt"


async def test_the_engines_own_paper_broker_is_never_evicted(clean_manager, db_session):
    """The live loop registers its PaperBroker under the literal key "paper".

    It has no DB row, so a naive "not in the wanted set -> drop it" would take
    the trading engine's own broker away from under it mid-run.
    """
    broker_manager._adapters["paper"] = FakeAdapter()  # noqa: SLF001

    result = await broker_manager.reconcile_connections(db_session)

    assert result["dropped"] == 0
    assert "paper" in broker_manager._adapters, "evicted the engine's own broker"  # noqa: SLF001


async def test_an_adapter_for_a_deleted_connection_is_dropped(
    clean_manager, db_session
):
    """A removed connection must stop answering from memory."""
    stale = "11111111-2222-3333-4444-555555555555"
    broker_manager._adapters[stale] = FakeAdapter()  # noqa: SLF001

    result = await broker_manager.reconcile_connections(db_session)

    assert result["dropped"] == 1
    assert stale not in broker_manager._adapters  # noqa: SLF001


# ---------------------------------------------------------------------------
# It must survive the conditions it exists for
# ---------------------------------------------------------------------------
async def test_backs_off_instead_of_hammering(clean_manager, db_session, monkeypatch):
    """A broker down for hours must not trigger a login attempt every minute."""
    attempts = {"n": 0}

    def always_fail(**_):
        attempts["n"] += 1
        raise RuntimeError("still down")

    monkeypatch.setattr("app.services.broker.manager._make_adapter", always_fail)
    row = _row(connected=True)
    db_session.add(row)
    await db_session.commit()

    for _ in range(20):
        await broker_manager.reconcile_connections(db_session)

    assert attempts["n"] < 20, "no backoff — retried on every single tick"
    assert attempts["n"] >= 2, "backed off so hard it effectively gave up"


async def test_never_raises_even_when_everything_fails(
    clean_manager, db_session, monkeypatch
):
    """A supervisor that dies on the first error supervises nothing."""
    def boom(**_):
        raise RuntimeError("catastrophe")

    monkeypatch.setattr("app.services.broker.manager._make_adapter", boom)
    db_session.add(_row(connected=True))
    await db_session.commit()

    result = await broker_manager.reconcile_connections(db_session)  # must not raise
    assert result["still_failing"] == 1
