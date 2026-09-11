"""B404 — an HTTP response body carried an upstream credential, and no redactor stood on that path.

`_secrets_filter` guards the log sink and `redact_for_storage` guards database columns. **An HTTP
response body passed through neither.** `calendar.py` put the upstream `httpx` error into a 502
detail; an `httpx.HTTPStatusError` renders the request URL; Finnhub authenticates with `?token=`
in that URL. So a failing upstream handed the Finnhub key to the caller — most often when the key
was already wrong or expired, which is when someone is most likely to be hitting the endpoint.

**These arms are built from the REAL serialisation, not from the redaction patterns.** The first
version of `redact_for_storage` passed its own arm while leaking four of five realistic Alpaca
shapes, because its fixtures were derived from its patterns. A fixture must come from what the
upstream library actually produces — here, `str()` of a genuine `httpx.HTTPStatusError`.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import BrokerConnectionError
from app.main import create_app

pytestmark = pytest.mark.asyncio

FINNHUB_KEY = "d1abcFAKEfinnhubKEY9x2q7w0"
ALPACA_KEY = "PKTEST1234567890ABCD"


def _real_upstream_error(key: str) -> httpx.HTTPStatusError:
    """A GENUINE `httpx.HTTPStatusError`, so its `str()` is what production would render."""
    request = httpx.Request("GET", f"https://finnhub.io/api/v1/calendar/economic?token={key}")
    response = httpx.Response(401, request=request)
    return httpx.HTTPStatusError("401 Unauthorized", request=request, response=response)


async def test_the_premise_a_real_httpx_error_DOES_carry_the_key():
    """**The control for every arm below.** If `str()` of a real `HTTPStatusError` did not contain
    the URL, none of these arms would be testing anything — they would pass on a leak that cannot
    happen. Asserted, not assumed."""
    exc = _real_upstream_error(FINNHUB_KEY)
    try:
        exc.response.raise_for_status()
    except httpx.HTTPStatusError as real:
        assert FINNHUB_KEY in str(real), (
            "httpx no longer renders the URL in its message; the leak this file guards may have "
            "closed upstream — say so rather than keep arms that test nothing"
        )


async def test_the_calendar_endpoint_does_not_return_the_upstream_key(client, monkeypatch):
    """**The instance.** A Finnhub 401 must not put the Finnhub key into the 502 body."""
    from app.api.routers import calendar as calendar_router
    from app.services.calendar import finnhub

    monkeypatch.setattr(calendar_router.app_settings, "finnhub_api_key", FINNHUB_KEY)

    async def _fail():
        request = httpx.Request("GET",
                                f"https://finnhub.io/api/v1/calendar/economic?token={FINNHUB_KEY}")
        httpx.Response(401, request=request).raise_for_status()

    monkeypatch.setattr(finnhub.calendar_service, "get_today_events", _fail)

    resp = await client.get("/api/calendar/today")

    assert resp.status_code == 502
    assert FINNHUB_KEY not in resp.text, "the upstream credential is in the response body"
    assert "HTTPStatusError" in resp.json()["detail"], "the diagnostic must survive the redaction"
    assert "401" in resp.json()["detail"], "and the upstream status with it"


def _app_with_leaking_routes():
    """The app with its REAL exception handlers, plus routes shaped like the eight sites."""
    app = create_app()

    async def http_exc():
        raise HTTPException(status_code=502,
                            detail=f"fetch failed: {_real_upstream_error(ALPACA_KEY)!s} "
                                   f"url=https://x/y?key_id={ALPACA_KEY}")

    async def broker_err():
        # `brokers.py` connect paths interpolate CONNECTION-ERROR text — where a credential rides.
        raise BrokerConnectionError(
            f"connect failed headers={{'APCA-API-KEY-ID': '{ALPACA_KEY}'}}", broker="alpaca",
        )

    app.add_api_route("/__b404/http", http_exc)
    app.add_api_route("/__b404/broker", broker_err)
    return app


async def test_the_CHOKEPOINT_redacts_an_HTTPException_detail():
    """**The contract, not the member.** Eight router sites interpolate an exception into a detail;
    fixing `calendar.py` alone leaves seven. Every problem+json body is built by `problem_response`,
    so that is where the redaction has to live."""
    async with AsyncClient(transport=ASGITransport(app=_app_with_leaking_routes()),
                           base_url="http://t") as c:
        resp = await c.get("/__b404/http")

    assert resp.status_code == 502
    assert ALPACA_KEY not in resp.text
    assert "[REDACTED]" in resp.text


async def test_the_CHOKEPOINT_redacts_a_TradingAIError_detail_too():
    """The OTHER handler. `BrokerError` is a `TradingAIError`, and its handler rendered
    `exc.detail` unredacted — the manager flagged it as unread, and it was not clean."""
    async with AsyncClient(transport=ASGITransport(app=_app_with_leaking_routes()),
                           base_url="http://t") as c:
        resp = await c.get("/__b404/broker")

    assert resp.status_code == 400
    assert ALPACA_KEY not in resp.text, "a broker error handed its credential to the client"


async def test_an_ordinary_detail_passes_through_UNCHANGED():
    """**The must-miss.** A chokepoint that blanks legitimate details makes every error useless and
    teaches clients to ignore them — the liveness-signal failure in a security control."""
    from app.core.exceptions import problem_response

    msg = "Alert not found: 7c1e0b2a is not an alert you own"
    assert problem_response(title="x", status=404, detail=msg)["detail"] == msg
