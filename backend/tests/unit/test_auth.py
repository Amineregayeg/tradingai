"""Unit tests for the API auth gate (app.api.deps).

The wider suite runs with AUTH_DISABLED=true so endpoint fixtures don't need a
token; these tests drive the gate directly with real settings values to prove
it fails closed.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import deps


async def test_current_user_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(deps.settings, "auth_disabled", False)
    monkeypatch.setattr(deps.settings, "api_auth_token", "s3cret-token")
    with pytest.raises(HTTPException) as ei:
        await deps.current_user(authorization=None)
    assert ei.value.status_code == 401


async def test_current_user_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(deps.settings, "auth_disabled", False)
    monkeypatch.setattr(deps.settings, "api_auth_token", "s3cret-token")
    with pytest.raises(HTTPException) as ei:
        await deps.current_user(authorization="Bearer wrong")
    assert ei.value.status_code == 401


async def test_current_user_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(deps.settings, "auth_disabled", False)
    monkeypatch.setattr(deps.settings, "api_auth_token", "s3cret-token")
    uid = await deps.current_user(authorization="Bearer s3cret-token")
    assert uid == "system"


async def test_current_user_bypass_when_disabled(monkeypatch):
    monkeypatch.setattr(deps.settings, "auth_disabled", True)
    monkeypatch.setattr(deps.settings, "api_auth_token", "")
    uid = await deps.current_user(authorization=None)
    assert uid == "system"


def test_assert_auth_configured_raises_when_open(monkeypatch):
    monkeypatch.setattr(deps.settings, "auth_disabled", False)
    monkeypatch.setattr(deps.settings, "api_auth_token", "")
    with pytest.raises(RuntimeError):
        deps.assert_auth_configured()


def test_assert_auth_configured_ok_with_token(monkeypatch):
    monkeypatch.setattr(deps.settings, "auth_disabled", False)
    monkeypatch.setattr(deps.settings, "api_auth_token", "s3cret-token")
    deps.assert_auth_configured()  # must not raise


def test_assert_auth_configured_ok_when_disabled(monkeypatch):
    monkeypatch.setattr(deps.settings, "auth_disabled", True)
    monkeypatch.setattr(deps.settings, "api_auth_token", "")
    deps.assert_auth_configured()  # must not raise
