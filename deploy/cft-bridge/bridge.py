#!/usr/bin/env python3
"""CFT bridge — a browser that answers HTTP.

WHY THIS EXISTS
---------------
Crypto Fund Trader sits behind Cloudflare bot protection that fingerprints the
TLS handshake. Measured, not assumed:

    plain httpx + valid token .................. 403 (cf-mitigated: challenge)
    plain httpx + token + browser User-Agent ... 403
    plain httpx + token + UA + session cookies . 403
    Playwright's own HTTP stack + token ........ 403
    fetch() executed INSIDE a real browser page  200  <- the only one that works

So a valid token is not a key we can carry away: it only works from inside the
browser that obtained it. Every CFT request has to originate in a real browser.

This service owns exactly one logged-in Chromium session and exposes it as a
tiny local HTTP API. The backend adapter then speaks ordinary HTTP to *this*,
and the browser problem stops leaking into the rest of the codebase.

WHY A SEPARATE SERVICE RATHER THAN IN THE API CONTAINER
  * The api container does a runtime `git clone` + `pip install` on every
    recreate. Adding Playwright + Chromium would put ~400MB and several minutes
    onto every deploy of an app that mostly has nothing to do with CFT.
  * A browser is a crash-prone, memory-hungry thing. Isolated here, it can die
    and restart without touching the trading engine.
  * It can be restarted, upgraded, or switched off independently.

SECURITY
  * Binds to the internal Docker network only — never published to the host.
  * Every request must carry BRIDGE_TOKEN. Without it the bridge is an open
    proxy into a funded trading account for anything else on the network.
  * Credentials arrive by env var, are used once at login, and are never logged.
  * The CFT session token is held in memory only and is never returned to
    callers or written to disk.

  * WRITES ARE REFUSED unless BRIDGE_ALLOW_TRADING=true. See the write-guard
    section below.

ON POLICY (this changed, and the reasoning is worth keeping)
An earlier version of this file said the bridge was "dumb transport" and that
every safety decision belonged in the backend, on the argument that a second
enforcement point is a second place for rules to disagree.

That is right for BUSINESS rules and wrong for the one rule that matters here.
All three backend guards — the is_simulation assert, the ALLOW_LIVE_TRADING
gate, observe_only — sit UPSTREAM of this process. The bridge is the last hop
before a funded account, so "the backend will have checked" is precisely the
assumption defence in depth exists to refuse. A bug past those checks, a
mistaken curl, or any other container on this network reaching the bridge would
otherwise place a real order.

So the bridge enforces exactly ONE thing, the narrowest possible: can this
request move money at all. It still makes no judgement about size, symbol,
direction or strategy — those stay in the backend where they are tested.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

from aiohttp import web
from playwright.async_api import async_playwright

LOG = logging.getLogger("cft-bridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CFT_HOST = os.getenv("CFT_HOST", "https://trading.cryptofundtrader.com").rstrip("/")
CFT_EMAIL = os.getenv("CFT_EMAIL", "")
CFT_PASSWORD = os.getenv("CFT_PASSWORD", "")
BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN", "")
BRIDGE_PORT = int(os.getenv("BRIDGE_PORT", "8099"))

#: Re-login if the session has been up this long. The token is a JWT that
#: expires; refreshing on a schedule means the ~11s login cost is paid while
#: idle rather than in the middle of a trading decision.
SESSION_MAX_AGE_S = int(os.getenv("SESSION_MAX_AGE_S", str(6 * 3600)))

# ---------------------------------------------------------------------------
# WRITE GUARD — the last line before a real order on a funded account.
#
# Everything else that protects this account lives in the Python app:
# ExecutionService asserts is_simulation, _make_adapter forces observe_only
# unless ALLOW_LIVE_TRADING, and the adapter's _guard_trading refuses writes.
# All three are UPSTREAM of this process. The bridge is the last hop, and until
# now it would proxy any path and any method for anything holding its token — so
# a bug downstream of those checks, a mistaken curl, or any other container on
# the network reaching this service, would place a real order.
#
# Defence in depth means the innermost layer does not trust that the outer ones
# held. This guard is independent of every app-side flag on purpose: enabling
# trading has to be a deliberate act in TWO separate places (ALLOW_LIVE_TRADING
# on the api, BRIDGE_ALLOW_TRADING here), which no single mistake can satisfy.
# ---------------------------------------------------------------------------

#: Path fragments that CREATE, MODIFY or CLOSE a position — anything that moves
#: real money. Matched as substrings against the request path, so a renamed or
#: versioned CFT route still trips it.
WRITE_PATH_FRAGMENTS = (
    "/position/open",
    "/position/close",
    "/position/edit",
    "/position/modify",
    "/order",          # covers /order, /order/place, /active-orders mutations
    "/positions/close",
)

BRIDGE_ALLOW_TRADING = os.getenv("BRIDGE_ALLOW_TRADING", "false").strip().lower() == "true"


def is_write_request(method: str, path: str) -> bool:
    """True if this request could create or change a position.

    Deliberately conservative in two ways:

    * ANY non-GET method counts. A write dressed as PUT/PATCH/DELETE is still a
      write, and enumerating only POST would be an obvious gap.
    * A GET to a write path counts too. If CFT ever accepts a position action
      over GET (some Match-Trader routes do), a method-only check would sail
      past it.

    False negatives here place real orders; false positives only block a read
    the app can retry. The asymmetry decides the design.
    """
    lowered = (path or "").lower()
    if any(frag in lowered for frag in WRITE_PATH_FRAGMENTS):
        return True
    return (method or "GET").upper() != "GET"

#: A login takes ~11s (measured). Give it generous headroom before declaring
#: failure — a slow login that succeeds beats a fast failure that trades nothing.
LOGIN_TIMEOUT_MS = 90_000


class CFTSession:
    """One logged-in browser. All access is serialized through `_lock`.

    Playwright pages are not safe for concurrent use, and more importantly the
    engine must never fire two orders because two coroutines both thought they
    needed to re-login.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        self._token: str | None = None
        self._uuid: str | None = None
        self._logged_in_at: float = 0.0
        self.login_count = 0
        self.call_count = 0
        self.last_error: str | None = None

    # -- lifecycle ----------------------------------------------------------
    async def _launch(self) -> None:
        if self._browser is not None:
            return
        self._pw = await async_playwright().start()
        # headless=False under Xvfb: headless Chrome is detected and served the
        # "Just a moment..." challenge; a real headed browser passes cleanly.
        # This is the single most important line in the file.
        self._browser = await self._pw.chromium.launch(
            headless=False,
            channel="chromium",
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        self._ctx = await self._browser.new_context(
            locale="en-US", timezone_id="Europe/Paris",
            viewport={"width": 1440, "height": 900},
        )
        await self._ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        self._page = await self._ctx.new_page()

    async def _login(self) -> None:
        """Drive the real login form and capture the session token + system uuid.

        The token is never sent to us directly — it is read off the Authorization
        header of the app's own API calls once it starts making them.
        """
        if not CFT_EMAIL or not CFT_PASSWORD:
            raise RuntimeError("CFT_EMAIL / CFT_PASSWORD not configured")

        await self._launch()
        page = self._page
        found: dict[str, str | None] = {"token": None, "uuid": None}

        def on_response(resp) -> None:
            headers = {k.lower(): v for k, v in resp.request.headers.items()}
            tok = headers.get("auth-trading-api")
            if tok and not found["token"]:
                found["token"] = tok
                m = re.search(r"/mtr-api/([0-9a-f-]{36})/", resp.url)
                if m:
                    found["uuid"] = m.group(1)

        page.on("response", on_response)
        try:
            await page.goto(f"{CFT_HOST}/", wait_until="domcontentloaded", timeout=LOGIN_TIMEOUT_MS)
            await page.wait_for_selector("input[type=password]", timeout=LOGIN_TIMEOUT_MS)

            email_sel = "input[type=email], input[type=text]"
            # press_sequentially, not fill(): the login form is a controlled
            # React component and validates on keystrokes. fill() can leave its
            # internal state empty, which shows up as "Value must be a valid
            # email" and a disabled Sign In button.
            await page.locator(email_sel).first.click()
            await page.locator(email_sel).first.press_sequentially(CFT_EMAIL, delay=35)
            await page.locator("input[type=password]").first.click()
            await page.locator("input[type=password]").first.press_sequentially(CFT_PASSWORD, delay=35)
            await page.wait_for_timeout(400)

            await page.get_by_role("button", name=re.compile("sign ?in|log ?in", re.I)).first.click(
                timeout=20_000
            )
            await page.wait_for_url(re.compile(r"/app/"), timeout=LOGIN_TIMEOUT_MS)

            # The token appears only once the app starts calling its own API.
            for _ in range(40):
                if found["token"] and found["uuid"]:
                    break
                await page.wait_for_timeout(500)
        finally:
            page.remove_listener("response", on_response)

        if not (found["token"] and found["uuid"]):
            raise RuntimeError("logged in but never observed an API token — CFT UI may have changed")

        self._token, self._uuid = found["token"], found["uuid"]
        self._logged_in_at = time.time()
        self.login_count += 1
        # uuid is not secret (it is in every URL); the token never gets logged.
        LOG.info("CFT session established (uuid=%s, login #%d)", self._uuid, self.login_count)

    async def _ensure(self, force: bool = False) -> None:
        stale = (time.time() - self._logged_in_at) > SESSION_MAX_AGE_S
        if force or self._token is None or stale:
            if stale and self._token is not None:
                LOG.info("session past max age — refreshing")
            await self._teardown()
            await self._login()

    async def _teardown(self) -> None:
        for closer in (self._ctx, self._browser):
            try:
                if closer:
                    await closer.close()
            except Exception:  # noqa: BLE001 - teardown must not raise
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
        self._pw = self._browser = self._ctx = self._page = None
        self._token = self._uuid = None

    # -- the actual work ----------------------------------------------------
    async def call(self, method: str, path: str, body: Any = None) -> dict:
        """Run one CFT API request inside the page. Returns {status, body}.

        `path` is relative to the account root, e.g. "/balance" ->
        /mtr-api/{uuid}/balance. Absolute paths starting with /mtr-api or
        /market-data-api are passed through so callers can reach endpoints that
        are not account-scoped.
        """
        async with self._lock:
            await self._ensure()
            try:
                result = await self._fetch(method, path, body)
            except Exception as exc:  # noqa: BLE001 - page may be dead; retry once
                LOG.warning("call failed (%s); re-establishing session", type(exc).__name__)
                await self._ensure(force=True)
                result = await self._fetch(method, path, body)

            # A 401/403 means the token expired mid-session. One forced re-login
            # and retry, so a routine expiry is invisible to the caller rather
            # than surfacing as a failed trade.
            if result["status"] in (401, 403):
                LOG.info("got %s — refreshing session and retrying once", result["status"])
                await self._ensure(force=True)
                result = await self._fetch(method, path, body)

            self.call_count += 1
            return result

    async def _fetch(self, method: str, path: str, body: Any) -> dict:
        if path.startswith("/mtr-api/") or path.startswith("/market-data-api/"):
            url = path
        else:
            url = f"/mtr-api/{self._uuid}{path if path.startswith('/') else '/' + path}"

        # fetch() runs in the page's own context, so it inherits the browser's
        # TLS fingerprint, cookies and origin. This is the whole trick.
        return await self._page.evaluate(
            """async ([url, method, token, body]) => {
                const opts = {
                    method,
                    headers: {
                        'Auth-trading-api': token,
                        'Accept': 'application/json',
                        ...(body ? {'Content-Type': 'application/json'} : {}),
                    },
                };
                if (body) opts.body = JSON.stringify(body);
                const r = await fetch(url, opts);
                const text = await r.text();
                return {status: r.status, body: text};
            }""",
            [url, method.upper(), self._token, body],
        )

    def status(self) -> dict:
        age = time.time() - self._logged_in_at if self._logged_in_at else None
        return {
            "logged_in": self._token is not None,
            "uuid": self._uuid,               # not secret; appears in every URL
            "session_age_s": round(age, 1) if age is not None else None,
            "session_max_age_s": SESSION_MAX_AGE_S,
            "logins": self.login_count,
            "calls": self.call_count,
            "last_error": self.last_error,
            # Surfaced so the dashboard can show, without anyone guessing,
            # whether this bridge is currently able to move real money.
            "trading_enabled": BRIDGE_ALLOW_TRADING,
        }


SESSION = CFTSession()


def _authorized(request: web.Request) -> bool:
    if not BRIDGE_TOKEN:
        return False  # fail closed: unconfigured means unusable, never open
    supplied = request.headers.get("X-Bridge-Token", "")
    # constant-time-ish compare; these are short strings but no reason to leak
    return len(supplied) == len(BRIDGE_TOKEN) and all(
        a == b for a, b in zip(supplied, BRIDGE_TOKEN)
    )


async def handle_health(request: web.Request) -> web.Response:
    """Unauthenticated liveness only — deliberately reveals nothing about the
    account or session. Used by the container healthcheck."""
    return web.json_response({"ok": True, "service": "cft-bridge"})


async def handle_status(request: web.Request) -> web.Response:
    if not _authorized(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response(SESSION.status())


async def handle_call(request: web.Request) -> web.Response:
    if not _authorized(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "invalid JSON"}, status=400)

    path = payload.get("path")
    if not path:
        return web.json_response({"error": "path is required"}, status=400)
    method = payload.get("method", "GET")

    # WRITE GUARD. Refused BEFORE the request reaches the browser, so a blocked
    # order never touches CFT at all. 403 (not 401) to distinguish "you are
    # authenticated but this action is disabled" from "your token is wrong".
    if is_write_request(method, path) and not BRIDGE_ALLOW_TRADING:
        LOG.warning("BLOCKED write request: %s %s (BRIDGE_ALLOW_TRADING is off)", method, path)
        return web.json_response(
            {
                "error": "trading is disabled on this bridge",
                "detail": (
                    f"{method} {path} would create or modify a position. Set "
                    "BRIDGE_ALLOW_TRADING=true to permit it — and note the app "
                    "has its own separate ALLOW_LIVE_TRADING gate."
                ),
                "blocked": True,
            },
            status=403,
        )

    try:
        result = await SESSION.call(method, path, payload.get("body"))
        SESSION.last_error = None
        return web.json_response(result)
    except Exception as exc:  # noqa: BLE001 - report, never crash the service
        SESSION.last_error = f"{type(exc).__name__}: {exc}"
        LOG.error("bridge call failed: %s", SESSION.last_error)
        return web.json_response({"error": SESSION.last_error}, status=502)


async def handle_reconnect(request: web.Request) -> web.Response:
    """Force a fresh login. For operators; also lets the backend recover
    deliberately rather than waiting for the next failure."""
    if not _authorized(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        async with SESSION._lock:  # noqa: SLF001 - same module
            await SESSION._ensure(force=True)  # noqa: SLF001
        return web.json_response({"ok": True, **SESSION.status()})
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": str(exc)}, status=502)


def main() -> None:
    if not BRIDGE_TOKEN:
        raise SystemExit(
            "BRIDGE_TOKEN is not set. Refusing to start: without it this service "
            "is an unauthenticated proxy into a funded trading account."
        )
    app = web.Application()
    app.add_routes([
        web.get("/health", handle_health),
        web.get("/status", handle_status),
        web.post("/call", handle_call),
        web.post("/reconnect", handle_reconnect),
    ])
    LOG.info("cft-bridge listening on :%d (host=%s)", BRIDGE_PORT, CFT_HOST)
    # State this loudly at boot. "Is trading on?" should be answerable from the
    # logs alone, not by reading env vars off a running container.
    if BRIDGE_ALLOW_TRADING:
        LOG.warning("TRADING IS ENABLED on this bridge — writes will reach the real account")
    else:
        LOG.info("Trading disabled (BRIDGE_ALLOW_TRADING off) — reads only, writes are refused")
    web.run_app(app, port=BRIDGE_PORT, print=None)


if __name__ == "__main__":
    main()
