"""B368 — the API must be able to EMIT the credential blob the adapter accepts.

**WHY THIS FILE IS AN INTEGRATION TEST AND WHY IT DRIVES `connect_broker`.**

`_make_adapter` reads `token` and `mt5_account_id` from the credential blob. `connect_broker`
built that blob from `api_key / api_secret / email / password / base_url` and **never wrote either
field**, so the only blob that worked was one the API could not produce: an MT5 connection could be
created only by writing the `broker_connections` row straight into the database.

> **It survived two audits because both tested that the ADAPTER ACCEPTS a correct blob, and
> neither tested that the API can EMIT one.** A hand-built blob stood in for the producer both
> times — `B356`'s axis one layer out, and `B256`'s rule that a differential over synthetic inputs
> cannot test a producer.

**So an arm here that constructs the blob by hand would reproduce exactly the hole it exists to
close.** Every arm below goes through `connect_broker` and reads back what was actually stored.
"""
from __future__ import annotations

import json

import pytest

from app.core.exceptions import BrokerConnectionError
from app.core.security import decrypt_credentials
from app.schemas.broker import BrokerConnectRequest
from app.services.broker.manager import BrokerManager, _make_adapter
from app.services.broker.mt5 import MetaTrader5Adapter

pytestmark = pytest.mark.asyncio


def _request(**over) -> BrokerConnectRequest:
    base = dict(broker="mt5", token="tok-abc", mt5_account_id="acct-123",
                environment="demo", label="MT5 demo")
    base.update(over)
    return BrokerConnectRequest(**base)


async def test_connect_broker_STORES_the_token_and_account_id_the_factory_reads(db_session):
    """The blob the API writes must be one `_make_adapter` can build an adapter from.

    **This is the join B368 is about**, and it is asserted end to end: the request goes through
    `connect_broker`, the row is read back, decrypted through the same `decrypt_credentials` route
    every other blob uses, and handed to the factory unmodified.
    """
    manager = BrokerManager()
    try:
        await manager.connect_broker(db_session, user_id="u1", request=_request())
    except BrokerConnectionError:
        # Connecting reaches the venue and cannot succeed here. The row is what this asserts, and
        # it is written before the adapter is built.
        pass

    from sqlalchemy import select
    from app.models.broker_connection import BrokerConnection

    row = (await db_session.execute(select(BrokerConnection))).scalars().first()
    assert row is not None, "connect_broker persisted no connection row"

    creds = json.loads(decrypt_credentials(row.encrypted_creds))
    assert creds.get("token") == "tok-abc", (
        "the API stored no `token`, so the only blob the factory accepts is one it cannot write"
    )
    assert creds.get("mt5_account_id") == "acct-123"

    # THE ACTUAL JOIN: the stored blob, unmodified, must construct the adapter.
    adapter = _make_adapter("mt5", creds, creds["mt5_account_id"], "demo")
    assert isinstance(adapter, MetaTrader5Adapter)


async def test_the_api_key_FORM_does_not_silently_produce_a_broken_connection(db_session):
    """`api_key` is NOT a third fallback for the token, and the refusal says so.

    Overloading it was the cheaper fix and was rejected: `api_key` means an exchange API key on
    every other broker here, and one field carrying two unrelated credentials is `B184` at the
    inbound surface — the same argument `B360` makes for the token having exactly one source.
    """
    manager = BrokerManager()
    with pytest.raises(BrokerConnectionError) as exc:
        await manager.connect_broker(
            db_session, user_id="u1",
            request=BrokerConnectRequest(broker="mt5", api_key="tok-in-the-wrong-field",
                                         account_id="acct-123"),
        )
    assert "not in `api_key`" in str(exc.value).replace("NOT", "not")


async def test_a_missing_account_id_REFUSES_BEFORE_a_row_is_written(db_session):
    """The boundary refusal must precede persistence, not follow it.

    `connect_broker` encrypts and writes the row at step 1 and builds the adapter at step 2, so
    deferring to the factory's refusal would leave a connection row behind for a request that was
    never viable.
    """
    from sqlalchemy import select
    from app.models.broker_connection import BrokerConnection

    manager = BrokerManager()
    with pytest.raises(BrokerConnectionError, match="ACCOUNT ID"):
        await manager.connect_broker(
            db_session, user_id="u1", request=_request(mt5_account_id=None, account_id=""),
        )
    rows = (await db_session.execute(select(BrokerConnection))).scalars().all()
    assert rows == [], "a row was persisted for a request that was refused"


async def test_a_NON_mt5_broker_is_UNAFFECTED_by_the_new_boundary_check(db_session):
    """The must-MISS. A guard added for one broker is one edit from refusing the others.

    `cft` supplies neither `token` nor `mt5_account_id` and must still be accepted here.
    """
    manager = BrokerManager()
    try:
        await manager.connect_broker(
            db_session, user_id="u1",
            request=BrokerConnectRequest(broker="cft", email="e", password="p",
                                         server="https://host/mtr-api/uuid",
                                         environment="live"),
        )
    except BrokerConnectionError as exc:
        assert "MetaApi" not in str(exc), (
            f"the MT5 boundary check rejected a non-MT5 broker: {exc}"
        )
