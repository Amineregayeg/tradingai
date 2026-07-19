"""The /ws WebSocket auth: single-use ticket (not the master token in the URL).

Covers the Level-2 finding (WS must require auth) AND the re-verify finding (the
master token must NOT be accepted in the URL query — it leaks to access logs; a
short-lived ticket is used instead).
"""
from __future__ import annotations

from app.api.routers import ws as ws_router
from app.core import ws_tickets


class _FakeWS:
    def __init__(self, query: dict | None = None, headers: dict | None = None):
        self.query_params = query or {}
        self.headers = headers or {}


def test_open_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", True)
    assert ws_router._ws_authorized(_FakeWS()) is True


def test_rejects_missing_credential(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", False)
    monkeypatch.setattr(ws_router.settings, "api_auth_token", "s3cret")
    assert ws_router._ws_authorized(_FakeWS()) is False


def test_rejects_master_token_in_query(monkeypatch):
    # The whole point of the ticket: the master token in ?token= is NOT accepted.
    monkeypatch.setattr(ws_router.settings, "auth_disabled", False)
    monkeypatch.setattr(ws_router.settings, "api_auth_token", "s3cret")
    assert ws_router._ws_authorized(_FakeWS(query={"token": "s3cret"})) is False


def test_accepts_valid_ticket(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", False)
    monkeypatch.setattr(ws_router.settings, "api_auth_token", "s3cret")
    ticket = ws_tickets.mint()
    assert ws_router._ws_authorized(_FakeWS(query={"ticket": ticket})) is True


def test_ticket_is_single_use(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", False)
    monkeypatch.setattr(ws_router.settings, "api_auth_token", "s3cret")
    ticket = ws_tickets.mint()
    assert ws_router._ws_authorized(_FakeWS(query={"ticket": ticket})) is True
    # second use must fail — the ticket was consumed
    assert ws_router._ws_authorized(_FakeWS(query={"ticket": ticket})) is False


def test_rejects_unknown_ticket(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", False)
    monkeypatch.setattr(ws_router.settings, "api_auth_token", "s3cret")
    assert ws_router._ws_authorized(_FakeWS(query={"ticket": "not-a-real-ticket"})) is False


def test_accepts_bearer_header_for_non_browser(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", False)
    monkeypatch.setattr(ws_router.settings, "api_auth_token", "s3cret")
    assert ws_router._ws_authorized(_FakeWS(headers={"authorization": "Bearer s3cret"})) is True


def test_consume_rejects_empty():
    assert ws_tickets.consume("") is False
