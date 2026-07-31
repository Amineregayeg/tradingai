"""A rejected broker connection must say WHY.

Real failure, hit while connecting a CryptoFundTrader account: the user picked
"Practice" from the environment dropdown and got

    An unexpected error occurred. Please try again later.

The backend had in fact produced a precise, actionable sentence —
"CryptoFundTrader has no 'practice' environment — only 'live' exists" — but it
arrived as a bare ValueError, which no handler caught, so it fell through to the
generic 500 handler and the message was replaced.

That is worse than an unhelpful error. It hides a perfect explanation, and its
advice ("try again later") can never work, because the request is invalid rather
than the server unavailable. Diagnosing it required SSH access to read the
container logs, which the person using the app will not have.

These tests pin the shape of the answer, not just the status code: the reason has
to reach the caller.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _connect(client, **overrides) -> tuple[int, str]:
    payload = {
        "broker": "cryptofundtrader",
        "email": "probe@example.invalid",
        "password": "irrelevant",
        "environment": "live",
        "observe_only": True,
        **overrides,
    }
    resp = await client.post("/api/brokers", json=payload)
    body = resp.json() if resp.content else {}
    return resp.status_code, str(body.get("detail", body))


async def test_impossible_environment_explains_itself(client):
    """The exact failure a user hit. 400 + the real reason, never a bare 500."""
    status, detail = await _connect(client, environment="practice")

    assert status != 500, "an invalid environment surfaced as a server error"
    assert status == 400, f"expected 400 for an invalid request, got {status}"
    assert "practice" in detail.lower(), f"the rejected value is not named: {detail!r}"
    assert "live" in detail.lower(), f"the valid alternative is not named: {detail!r}"
    assert "unexpected error" not in detail.lower(), (
        "the generic 500 message replaced the real explanation"
    )


async def test_unsupported_broker_explains_itself(client):
    """OANDA/Alpaca/MetaAPI were offered by the UI but cannot be constructed.

    The dropdown no longer lists them, but the API must still answer clearly —
    a stored connection, a scripted call, or a stale browser tab can all send one.
    """
    status, detail = await _connect(client, broker="alpaca")

    assert status != 500, "an unsupported broker surfaced as a server error"
    assert status == 400
    assert "alpaca" in detail.lower(), f"the rejected broker is not named: {detail!r}"
    assert "unexpected error" not in detail.lower()


async def test_valid_config_is_not_rejected_as_invalid(client):
    """Guard against over-correction.

    A well-formed request must NOT come back 400. It will still fail — there are
    no real credentials here and CFT sits behind bot protection — but as a
    connection/upstream failure (502), which is a different class of problem and
    must stay distinguishable from "you configured this wrong".
    """
    status, detail = await _connect(client)

    assert status != 400, (
        f"a valid configuration was rejected as invalid: {detail!r}"
    )
    assert status in (201, 502), f"unexpected status {status}: {detail!r}"
    if status == 502:
        assert "could not connect" in detail.lower()
