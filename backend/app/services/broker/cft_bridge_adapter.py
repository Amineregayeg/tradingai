"""CryptoFundTrader adapter that reaches CFT through a real browser.

Subclasses :class:`CryptoFundTraderAdapter` and replaces ONLY the transport and
the login handshake. Everything that interprets CFT's data — balance parsing,
position mapping, ``BTC/USD`` ↔ ``BTCUSDT.cft`` symbol translation, the
observe-only guard, quote polling — is inherited unchanged, along with the
existing test suite that covers it.

That split is the point. The Cloudflare problem is a *transport* problem; letting
it leak into the business logic would mean maintaining two adapters that drift.

See ``cft_bridge_transport`` for the measurements that forced this design, and
``deploy/cft-bridge/bridge.py`` for the service that owns the browser.
"""
from __future__ import annotations

from app.core.exceptions import BrokerConnectionError
from app.core.logging import logger
from app.services.broker.cft_bridge_transport import BridgeTransport
from app.services.broker.cryptofundtrader import CryptoFundTraderAdapter


class CFTBridgeAdapter(CryptoFundTraderAdapter):
    """CFT via the browser bridge. Identical behaviour, different plumbing."""

    broker_name = "cryptofundtrader"

    def __init__(
        self,
        *args,
        bridge_url: str | None = None,
        bridge_token: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        # Replace the httpx client the parent built. Everything downstream calls
        # self._client.get/post and cannot tell the difference.
        self._client.aclose  # noqa: B018 - documents the object being replaced
        self._bridge = BridgeTransport(bridge_url=bridge_url, bridge_token=bridge_token)
        self._client = self._bridge

    # ------------------------------------------------------------------
    async def connect(self) -> None:
        """Adopt the bridge's existing browser session.

        The parent's ``connect()`` POSTs credentials to ``/mtr-core-edge/login``
        and reads ``tradingAccounts`` from the reply. That cannot work here for
        two reasons:

        1. The POST itself would be blocked by Cloudflare — the very problem the
           bridge exists to solve.
        2. The browser app does not expose that response to us anyway. The
           session token is observed on the ``Auth-trading-api`` header of the
           app's own subsequent API calls, which is how the bridge captures it.

        So instead of logging in, we ask the bridge which session it already
        holds and adopt its system UUID. Credentials never travel this path —
        only the bridge holds them, and only for its login form.
        """
        logger.info(
            "Connecting to Crypto Fund Trader via browser bridge",
            bridge=self._bridge.bridge_url,
            account_id=self._account_id or "(bridge-selected)",
            observe_only=self.observe_only,
        )

        status = await self._bridge.status()
        if not status.get("reachable"):
            raise BrokerConnectionError(
                "CFT bridge is not running",
                broker=self.broker_name,
                detail=(
                    f"{self._bridge.bridge_url}: {status.get('error')}. "
                    "Start the cft-bridge service (deploy/compose.cft-bridge.yaml)."
                ),
            )
        if not status.get("authorized"):
            raise BrokerConnectionError(
                "CFT bridge rejected our token",
                broker=self.broker_name,
                detail="CFT_BRIDGE_TOKEN must match the bridge's BRIDGE_TOKEN.",
            )

        uuid = status.get("uuid")
        if not status.get("logged_in") or not uuid:
            # The bridge logs in lazily on first call; ask it to do so now so a
            # failure surfaces here, at connect time, rather than on the first
            # trading decision.
            logger.info("Bridge has no session yet — asking it to log in")
            refreshed = await self._bridge.reconnect()
            uuid = refreshed.get("uuid")
            if not refreshed.get("logged_in") or not uuid:
                raise BrokerConnectionError(
                    "CFT bridge could not establish a session",
                    broker=self.broker_name,
                    detail=str(refreshed.get("error") or refreshed),
                )

        self._system_uuid = uuid
        # The bridge injects the real token into every request. A placeholder
        # here keeps the parent's "am I connected" checks satisfied without
        # implying we hold a usable credential — we do not, and a copy of the
        # browser's token would not work from this process anyway.
        self._token = "bridge-managed"

        # Validate for real: fetch the balance. Adopting a session and declaring
        # success without one round-trip would report "connected" for a bridge
        # whose browser has since died.
        account = await self.get_account()
        self._currency = account.currency or self._currency

        if not self._group:
            try:
                resp = await self._client.get(self._api("/group"))
                if resp.status_code == 200:
                    self._group = self._parse_group(resp.text)
            except Exception as exc:  # noqa: BLE001 - group only affects quotes
                logger.warning("Could not read account group", error=str(exc))

        self.connected = True
        logger.info(
            "Crypto Fund Trader connected via bridge",
            uuid=self._system_uuid,
            currency=self._currency,
            group=self._group or "(unknown)",
            balance=account.balance,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_group(raw: str) -> str:
        """Extract the group NAME from whatever ``/group`` returned.

        Verified against the live account: this endpoint answers with a large
        JSON object — ``{"id": "realRLCusd-B6", "currency": "USD", "symbols":
        {...hundreds of instruments...}}`` — not the bare string the original
        adapter assumed. Taking ``.text`` wholesale stored ~290KB of instrument
        definitions as the "group name", which is then sent as ``groupName`` on
        every quote request.

        Falls back to the raw string (trimmed) if it is not JSON, so a future
        change back to a plain response still works.
        """
        import json as _json

        raw = (raw or "").strip()
        if not raw:
            return ""
        try:
            parsed = _json.loads(raw)
        except ValueError:
            return raw.strip('"')
        if isinstance(parsed, str):
            return parsed
        if isinstance(parsed, dict):
            for key in ("id", "name", "group", "groupName"):
                value = parsed.get(key)
                if isinstance(value, str) and value:
                    return value
        return ""

    # ------------------------------------------------------------------
    async def disconnect(self) -> None:
        """Close our client to the bridge — never the bridge's browser.

        The browser session is shared and expensive (~11s to rebuild). One
        adapter going away must not cost every other caller a re-login.
        """
        self.connected = False
        await self._bridge.aclose()

    async def bridge_status(self) -> dict:
        """Session health for the connection-health surface (task 4.3)."""
        return await self._bridge.status()
