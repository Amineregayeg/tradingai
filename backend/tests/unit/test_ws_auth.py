"""The /ws WebSocket must require the bearer token (it streams live positions,
alerts, kill-switch events). Regression for the Level-2 finding that it was open.
"""
from __future__ import annotations

from app.api.routers import ws as ws_router


class _FakeWS:
    def __init__(self, query: dict | None = None, headers: dict | None = None):
        self.query_params = query or {}
        self.headers = headers or {}


def test_open_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", True)
    assert ws_router._ws_authorized(_FakeWS()) is True


def test_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", False)
    monkeypatch.setattr(ws_router.settings, "api_auth_token", "s3cret")
    assert ws_router._ws_authorized(_FakeWS()) is False


def test_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", False)
    monkeypatch.setattr(ws_router.settings, "api_auth_token", "s3cret")
    assert ws_router._ws_authorized(_FakeWS(query={"token": "nope"})) is False


def test_accepts_query_token(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", False)
    monkeypatch.setattr(ws_router.settings, "api_auth_token", "s3cret")
    assert ws_router._ws_authorized(_FakeWS(query={"token": "s3cret"})) is True


def test_accepts_bearer_header(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", False)
    monkeypatch.setattr(ws_router.settings, "api_auth_token", "s3cret")
    assert ws_router._ws_authorized(_FakeWS(headers={"authorization": "Bearer s3cret"})) is True


def test_rejects_when_no_token_configured(monkeypatch):
    monkeypatch.setattr(ws_router.settings, "auth_disabled", False)
    monkeypatch.setattr(ws_router.settings, "api_auth_token", "")
    assert ws_router._ws_authorized(_FakeWS(query={"token": "anything"})) is False
