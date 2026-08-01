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

DELIBERATELY NOT IMPLEMENTED HERE: any notion of "should this order be allowed".
The bridge is dumb transport. Every safety decision — observe_only, the
ALLOW_LIVE_TRADING gate, the is_simulation contract — stays in the backend where
it is tested. A bridge that also enforced policy would be a second, untested
place for those rules to disagree.
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
    web.run_app(app, port=BRIDGE_PORT, print=None)


if __name__ == "__main__":
    main()
