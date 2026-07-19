"""Short-lived, single-use WebSocket tickets.

Browsers can't set an Authorization header on a WS upgrade, so the handshake
needs the credential in the URL. Putting the long-lived MASTER token there leaks
it into access logs and browser history. Instead the client first calls an
authenticated HTTP endpoint to mint a one-time ticket (short TTL, single use)
and connects with `?ticket=<ticket>`. A leaked ticket is worthless seconds later
and can't be replayed.

In-memory store — correct for the single-worker uvicorn deployment. If this ever
runs multi-worker, back it with Redis.
"""
from __future__ import annotations

import secrets
import time

_TTL_SECONDS = 30.0
_MAX_TICKETS = 1000  # backstop against unbounded growth
_tickets: dict[str, float] = {}  # ticket -> expiry (monotonic clock)


def _prune(now: float) -> None:
    for k in [k for k, exp in _tickets.items() if exp < now]:
        _tickets.pop(k, None)


def mint() -> str:
    """Create a fresh single-use ticket valid for _TTL_SECONDS."""
    now = time.monotonic()
    _prune(now)
    if len(_tickets) >= _MAX_TICKETS:
        # drop the soonest-expiring to bound memory (DoS backstop)
        oldest = min(_tickets, key=_tickets.get)
        _tickets.pop(oldest, None)
    ticket = secrets.token_urlsafe(24)
    _tickets[ticket] = now + _TTL_SECONDS
    return ticket


def consume(ticket: str) -> bool:
    """Validate AND invalidate a ticket. True only if it existed and is unexpired."""
    if not ticket:
        return False
    now = time.monotonic()
    _prune(now)
    exp = _tickets.pop(ticket, None)  # single-use: removed on read
    return exp is not None and exp >= now
