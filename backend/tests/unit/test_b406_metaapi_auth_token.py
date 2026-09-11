"""B406 — MetaApi's websocket URL carries `?auth-token=<jwt>`, and the redactor did not recognise it.

`_redact`'s query-string rule anchors on `?` or `&` IMMEDIATELY before the name. In
`?auth-token=` the character before `token` is a hyphen, so the plain `token` alternative never
fired — **right about the name, wrong about what precedes it**, the same shape as the first
`APCA-API-*` pattern (right about the name, wrong about the punctuation after it).

Path: `manager.py:460` -> `brokers.py:88`/`:173` -> `problem_response`. Unreachable in production
today (one CryptoFundTrader connection, zero MT5 rows), so severity is low — but the redactor is
shared by every path, and a hole in it is a hole everywhere.

**The URL shape comes from the INSTALLED SDK, not from my typing.** The premise arm reads the SDK
source and asserts it still builds `?auth-token=`; the other arms render that exact format with a
JWT-shaped token, because a real MetaApi token is a JWT and the bare-token rule excludes `.`.
"""
from __future__ import annotations

import inspect
import re

import pytest

from app.core.logging import redact_for_response, redact_for_storage

# JWT-shaped: three base64url segments joined by dots. The bare-token rule's character class
# excludes `.`, so without the named pattern a real token is caught segment-by-segment at best.
_JWT = ("eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCJ9"
        ".eyJfaWQiOiJhYmMxMjMiLCJ0b2tlbklkIjoiMjAyNi0wOSJ9"
        ".Xk2pQ9vR7sT1uW3yZ5aB8cD0eF2gH4iJ6kL8mN0oP")


def _sdk_url_format() -> str:
    """The f-string the installed SDK uses, read from its source rather than copied by hand."""
    from metaapi_cloud_sdk.clients.metaapi import metaapi_websocket_client as mod

    src = inspect.getsource(mod)
    m = re.search(r"url = f'\{server_url\}(\?auth-token=\{self\._token\}[^']*)'", src)
    assert m, "the SDK no longer builds ?auth-token= into its URL — re-read it before trusting B406"
    return m.group(1)


def test_the_premise_the_INSTALLED_SDK_builds_auth_token_into_its_url():
    """**The control for every arm below.** If the SDK stopped putting the token in the query string,
    these arms would guard a leak that cannot happen — and they must say so rather than pass."""
    fmt = _sdk_url_format()
    assert fmt.startswith("?auth-token=")


def _rendered(sep_first: bool = True) -> str:
    tail = _sdk_url_format().replace("{self._token}", _JWT)
    tail = re.sub(r"\{[^}]+\}", "X", tail)  # clientId / protocol placeholders
    return f"ConnectError: wss://mt-client-api-v1.london.agiliumtrade.ai/ws{tail}"


#: A single-segment ACCOUNT token — the SDK's other token type (`metaapi_client.py:29`: one segment
#: means `'account'`, three means a JWT `'api'` token). Chosen to sit OUTSIDE the bare-token rule's
#: reach: lowercase hex has no uppercase letter, so the backstop cannot see it.
_ACCOUNT_TOKEN = "5f3a9c1e7b2d4a6f8e0c1b3d"


def test_the_premise_the_SDK_has_a_SINGLE_SEGMENT_token_type():
    """The isolating arm below depends on account tokens being real. Read from the SDK, not assumed."""
    from metaapi_cloud_sdk.clients import metaapi_client

    src = inspect.getsource(metaapi_client)
    assert "split('.')) == 1" in src and "'account'" in src, (
        "the SDK no longer has a single-segment account token; the isolating arm tests nothing"
    )


def test_the_backstop_CANNOT_see_the_account_token():
    """**The reason the isolating arm is isolating, asserted rather than assumed.** If the bare-token
    rule caught this token on its own, the next arm would pass without the named pattern — which is
    exactly how the first version of this file passed 5/5 against the UNFIXED redactor."""
    assert _ACCOUNT_TOKEN in redact_for_response(f"opaque value {_ACCOUNT_TOKEN} in prose")


@pytest.mark.parametrize("redact", [redact_for_response, redact_for_storage])
def test_an_ACCOUNT_token_in_the_sdk_url_does_not_leak(redact):
    """**THE ARM THAT ISOLATES `auth[_-]?token`.** This is the one that fails without the fix."""
    out = redact(_rendered().replace(_JWT, _ACCOUNT_TOKEN))
    assert _ACCOUNT_TOKEN not in out, f"an account token survived {redact.__name__}"


@pytest.mark.parametrize("redact", [redact_for_response, redact_for_storage])
def test_a_JWT_in_the_sdk_url_does_not_leak(redact):
    """**A REGRESSION GUARD, NOT A TEST OF THE NAMED RULE — said plainly.** A realistic JWT's three
    segments are each 32+ mixed-case characters with digits, so the bare-token backstop already
    redacts them; this arm passes with or without `auth[_-]?token`. It is kept because it pins that
    the COMBINED redactor handles the SDK's other token type, not because it proves B406's fix."""
    out = redact(_rendered())
    for segment in _JWT.split("."):
        assert segment not in out, f"a JWT segment survived {redact.__name__}: {segment[:12]}..."


def test_auth_token_after_an_AMPERSAND_is_caught_too():
    out = redact_for_response(f"wss://host/ws?clientId=1&auth-token={_ACCOUNT_TOKEN}")
    assert _ACCOUNT_TOKEN not in out, "isolated the same way: an account token the backstop cannot see"


def test_the_rest_of_the_url_survives():
    """**The must-miss.** Redacting the whole URL would destroy the diagnostic — which host, which
    region — and teach readers to ignore the field."""
    out = redact_for_response(_rendered())
    assert "agiliumtrade.ai" in out
    assert "clientId" in out
