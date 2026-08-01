"""/api/brokers/accounts — live account state, honestly reported.

This endpoint is what makes a connected broker *visible*: the platform could
reach Crypto Fund Trader before this existed, but nothing displayed it, so
"connected" was a claim with nothing behind it.

The properties worth protecting are about honesty, not correctness of arithmetic:

* A broker that cannot be reached is still LISTED, with reachable=false and the
  reason. Omitting it reads as "no such account".
* No figures are returned for an unreachable broker. A cached balance shown as
  current is the exact class of dishonesty this project was rebuilt to remove —
  and it is worse than a blank, because a blank prompts a question.
* One broker failing must not hide the others, and the endpoint must never 500.
  A status surface that fails when things are failing is useless precisely when
  it is needed.
"""
from __future__ import annotations

import pytest

from app.services.broker import broker_manager
from app.services.broker.base import Account

pytestmark = pytest.mark.asyncio


class FakeAdapter:
    broker_name = "fakebroker"
    observe_only = True

    def __init__(self, *, fail: str | None = None, is_sim: bool = False):
        self._fail = fail
        self.is_simulation = is_sim

    async def get_account(self) -> Account:
        if self._fail:
            raise RuntimeError(self._fail)
        return Account(
            account_id="ACC-1", broker=self.broker_name, balance=5090.95,
            equity=5090.95, currency="USD", open_trade_count=0, unrealized_pl=0.0,
        )


@pytest.fixture
def clean_manager():
    """Swap the adapter registry, then put it back."""
    original = dict(broker_manager._adapters)  # noqa: SLF001
    broker_manager._adapters.clear()           # noqa: SLF001
    yield broker_manager._adapters             # noqa: SLF001
    broker_manager._adapters.clear()           # noqa: SLF001
    broker_manager._adapters.update(original)  # noqa: SLF001


async def test_reports_a_reachable_account(clean_manager, client):
    clean_manager["conn-1"] = FakeAdapter()

    resp = await client.get("/api/brokers/accounts")
    assert resp.status_code == 200
    rows = resp.json()

    assert len(rows) == 1
    row = rows[0]
    assert row["reachable"] is True
    assert row["error"] is None
    assert row["account"]["balance"] == 5090.95
    assert row["account"]["currency"] == "USD"
    assert row["observe_only"] is True


async def test_unreachable_broker_is_listed_with_no_figures(clean_manager, client):
    """The core honesty property, in one test."""
    clean_manager["conn-1"] = FakeAdapter(fail="browser session died")

    rows = (await client.get("/api/brokers/accounts")).json()

    assert len(rows) == 1, "an unreachable broker was dropped from the list"
    row = rows[0]
    assert row["reachable"] is False
    assert row["account"] is None, "figures were returned for an unreachable broker"
    assert "browser session died" in row["error"], "the reason was not reported"


async def test_one_broken_broker_does_not_hide_the_others(clean_manager, client):
    clean_manager["ok"] = FakeAdapter()
    clean_manager["broken"] = FakeAdapter(fail="connection refused")

    rows = (await client.get("/api/brokers/accounts")).json()

    assert len(rows) == 2
    by_reach = {r["reachable"] for r in rows}
    assert by_reach == {True, False}
    good = next(r for r in rows if r["reachable"])
    assert good["account"]["balance"] == 5090.95


async def test_never_500s_when_every_broker_is_down(clean_manager, client):
    clean_manager["a"] = FakeAdapter(fail="down")
    clean_manager["b"] = FakeAdapter(fail="also down")

    resp = await client.get("/api/brokers/accounts")
    assert resp.status_code == 200, "a status endpoint must not fail when things fail"
    assert all(r["reachable"] is False for r in resp.json())


async def test_no_brokers_is_an_empty_list_not_an_error(clean_manager, client):
    resp = await client.get("/api/brokers/accounts")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_simulation_flag_is_surfaced(clean_manager, client):
    """The UI marks simulated accounts; it needs the truth from the adapter."""
    clean_manager["sim"] = FakeAdapter(is_sim=True)
    row = (await client.get("/api/brokers/accounts")).json()[0]
    assert row["is_simulation"] is True


async def test_transport_health_is_included_when_the_adapter_reports_it(
    clean_manager, client
):
    """The CFT bridge exposes bridge_status(); surfacing it distinguishes
    'the browser session died' from 'the broker rejected us'."""

    class WithTransport(FakeAdapter):
        async def bridge_status(self) -> dict:
            return {"reachable": True, "logged_in": True, "last_error": None}

    clean_manager["conn-1"] = WithTransport()
    row = (await client.get("/api/brokers/accounts")).json()[0]
    assert row["transport"]["logged_in"] is True


async def test_a_failing_transport_probe_does_not_break_the_row(clean_manager, client):
    """A health probe that throws must not take the account row with it."""

    class BadProbe(FakeAdapter):
        async def bridge_status(self) -> dict:
            raise RuntimeError("probe exploded")

    clean_manager["conn-1"] = BadProbe()
    row = (await client.get("/api/brokers/accounts")).json()[0]
    assert row["reachable"] is True, "a bad transport probe hid a working account"
    assert row["transport"]["reachable"] is False
