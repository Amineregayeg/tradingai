"""Transport that routes Crypto Fund Trader calls through a real browser.

WHY THIS IS NECESSARY (measured, not assumed)
---------------------------------------------
CFT sits behind Cloudflare bot protection that fingerprints the TLS handshake.
Every plain-HTTP route was tested against a *valid, freshly captured* session:

    httpx + token ............................. 403 (cf-mitigated: challenge)
    httpx + token + browser User-Agent ........ 403
    httpx + token + UA + all session cookies .. 403
    Playwright's own HTTP stack + token ....... 403
    fetch() executed INSIDE a real browser page  200  <- the only one that works

The token is therefore not a credential we can carry away and reuse: it is only
honoured on a connection that already looks like the browser which obtained it.
No amount of header-copying changes that, so the adapter cannot speak HTTP to
CFT directly — the requests must originate inside a browser.

`deploy/cft-bridge/` runs that browser as a separate service and exposes it as a
small local HTTP API. This class is the client for it, shaped to look like the
`httpx.AsyncClient` the adapter already uses, so the adapter's parsing logic —
balances, positions, symbol mapping, and its whole existing test suite — is
untouched. Only the transport changes.

WHY A SEPARATE SERVICE AND NOT AN IN-PROCESS BROWSER
Putting Playwright in the API container would add ~400MB and minutes of browser
download to every deploy of an app that is mostly unrelated to CFT, and a
browser crash would take the trading engine down with it. Out of process, the
browser can die, restart, or be upgraded on its own.

WHAT THIS DOES NOT DO
No safety policy lives here. observe_only, the ALLOW_LIVE_TRADING gate, and the
is_simulation contract all stay in the backend where they are tested. A
transport that also enforced rules would be a second, untested place for them to
disagree with the first.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.core.exceptions import BrokerConnectionError

DEFAULT_BRIDGE_URL = os.getenv("CFT_BRIDGE_URL", "http://cft-bridge:8100")

#: A cold bridge has to launch Chromium and log in (~11s measured, occasionally
#: slower under load). Anything less than this turns a routine session refresh
#: into a spurious failure.
DEFAULT_TIMEOUT_S = 120.0


class BridgeResponse:
    """Mimics the parts of ``httpx.Response`` the adapter actually touches.

    The full set, from grepping the adapter: ``.status_code``, ``.text``,
    ``.content``, ``.json()``, ``.headers``. Presenting exactly that surface is
    what lets the existing adapter run unmodified over a different transport.

    ``.content`` matters more than it looks: the adapter uses ``if not
    response.content`` to detect an empty body (some CFT endpoints answer 200
    with nothing). Omitting it raised AttributeError on the success path — a
    failure that only appears once a call actually succeeds, which is the worst
    time to find it.
    """

    def __init__(self, status_code: int, body: str, url: str = "") -> None:
        self.status_code = status_code
        self.text = body
        self.headers: dict[str, str] = {}
        self.url = url

    @property
    def content(self) -> bytes:
        """Raw body, as httpx would give it. Empty body -> falsy, as expected."""
        return (self.text or "").encode()

    def json(self) -> Any:
        return json.loads(self.text)

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<BridgeResponse {self.status_code} {self.url}>"


class BridgeTransport:
    """An ``httpx.AsyncClient``-shaped client that proxies through the bridge.

    Every CFT request becomes one POST to the bridge, which replays it inside
    its logged-in browser page and returns the raw status and body.
    """

    def __init__(
        self,
        bridge_url: str | None = None,
        bridge_token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.bridge_url = (bridge_url or DEFAULT_BRIDGE_URL).rstrip("/")
        self.bridge_token = bridge_token or os.getenv("CFT_BRIDGE_TOKEN", "")
        # `headers` exists because the adapter assigns the auth header onto its
        # client. Harmless here — the bridge owns the real token and injects it,
        # and it is deliberately NOT forwarded: the browser's token is the only
        # one CFT will honour, and shipping a second one around invites drift.
        self.headers: dict[str, str] = {}
        self._client = httpx.AsyncClient(
            base_url=self.bridge_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers={"Content-Type": "application/json"},
        )

    # ------------------------------------------------------------------
    async def _call(self, method: str, path: str, body: Any = None) -> BridgeResponse:
        if not self.bridge_token:
            raise BrokerConnectionError(
                "CFT bridge token is not configured",
                broker="cryptofundtrader",
                detail="Set CFT_BRIDGE_TOKEN so the backend can authenticate to the bridge.",
            )
        payload: dict[str, Any] = {"method": method, "path": path}
        if body is not None:
            payload["body"] = body
        try:
            resp = await self._client.post(
                "/call", json=payload, headers={"X-Bridge-Token": self.bridge_token}
            )
        except httpx.RequestError as exc:
            # The bridge itself is unreachable — a different failure from CFT
            # rejecting us, and it must not be reported as an auth problem.
            raise BrokerConnectionError(
                "CFT bridge is unreachable",
                broker="cryptofundtrader",
                detail=f"{self.bridge_url}: {exc}",
            ) from exc

        if resp.status_code == 401:
            raise BrokerConnectionError(
                "CFT bridge rejected our token",
                broker="cryptofundtrader",
                detail="CFT_BRIDGE_TOKEN does not match the bridge's BRIDGE_TOKEN.",
            )
        if resp.status_code >= 500:
            detail = resp.text[:300]
            raise BrokerConnectionError(
                "CFT bridge could not complete the request",
                broker="cryptofundtrader",
                detail=detail,
            )

        data = resp.json()
        return BridgeResponse(
            status_code=int(data.get("status", 502)),
            body=str(data.get("body", "")),
            url=path,
        )

    # -- the httpx.AsyncClient surface the adapter uses -------------------
    async def get(self, path: str, params: dict | None = None, **_: Any) -> BridgeResponse:
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            if query:
                path = f"{path}{'&' if '?' in path else '?'}{query}"
        return await self._call("GET", path)

    async def post(self, path: str, json: Any = None, **_: Any) -> BridgeResponse:  # noqa: A002
        return await self._call("POST", path, body=json)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    async def status(self) -> dict:
        """Bridge session health — for the connection-health surface.

        Returns ``{"reachable": False, ...}`` rather than raising: a health
        indicator that throws is a health indicator nobody calls.
        """
        try:
            resp = await self._client.get(
                "/status", headers={"X-Bridge-Token": self.bridge_token}
            )
            if resp.status_code == 401:
                return {"reachable": True, "authorized": False,
                        "error": "bridge token mismatch"}
            return {"reachable": True, "authorized": True, **resp.json()}
        except httpx.RequestError as exc:
            return {"reachable": False, "authorized": False, "error": str(exc)}

    async def reconnect(self) -> dict:
        """Force the bridge to establish a fresh browser session."""
        try:
            resp = await self._client.post(
                "/reconnect", headers={"X-Bridge-Token": self.bridge_token}
            )
            return resp.json()
        except httpx.RequestError as exc:
            raise BrokerConnectionError(
                "CFT bridge is unreachable",
                broker="cryptofundtrader",
                detail=str(exc),
            ) from exc
