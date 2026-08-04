"""The running commit must be reachable over HTTP (B3 / I6).

`/api/system/health` used to answer `"version": "0.1.0"` — a constant that had
never once changed. The point of these tests is that the field now tracks the
actual build, and that an unresolvable build is reported as unknown rather than
falling back to something that looks like an answer.

`/system/version` is deliberately separate from `/system/health`: during an
incident, "what is even deployed right now" should be answerable without
touching the database or Redis, which are the components you are probably
trying to diagnose.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core import build_info as bi

pytestmark = pytest.mark.asyncio

SHA = "abcdef0123456789abcdef0123456789abcdef01"


@pytest.fixture(autouse=True)
def clear_build_cache():
    bi.reset_cache()
    yield
    bi.reset_cache()


async def test_version_endpoint_reports_the_commit(client: AsyncClient, monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", SHA)
    monkeypatch.setenv("GIT_REF", SHA)
    bi.reset_cache()

    body = (await client.get("/api/system/version")).json()
    assert body["commit"] == SHA
    assert body["short"] == SHA[:9]
    assert body["known"] is True
    assert body["pinned"] is True


async def test_version_endpoint_needs_no_database(client: AsyncClient, monkeypatch):
    """It must answer while the things you are debugging are broken."""
    monkeypatch.setenv("GIT_COMMIT", SHA)
    bi.reset_cache()
    resp = await client.get("/api/system/version")
    assert resp.status_code == 200


async def test_health_carries_the_real_version(client: AsyncClient, monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", SHA)
    bi.reset_cache()

    body = (await client.get("/api/system/health")).json()
    assert body["version"] == SHA[:9], "health still reports a hardcoded version"
    assert body["build"]["commit"] == SHA


async def test_an_unknown_build_is_reported_as_unknown(client: AsyncClient, monkeypatch, tmp_path):
    """The failure being replaced was a confident wrong answer, so the honest
    blank matters more than the happy path."""
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.setenv(bi._SHA_FILE_ENV, str(tmp_path / "absent"))  # noqa: SLF001
    monkeypatch.setattr(bi, "_from_git", lambda: None)
    bi.reset_cache()

    body = (await client.get("/api/system/version")).json()
    assert body["commit"] == "unknown"
    assert body["known"] is False
    assert body["pinned"] is False


async def test_a_floating_deploy_is_not_reported_as_pinned(client: AsyncClient, monkeypatch):
    """GIT_REF=main resolves to a real commit that will be a DIFFERENT commit
    tomorrow. Reporting that as pinned would misrepresent it as reproducible."""
    monkeypatch.setenv("GIT_COMMIT", SHA)
    monkeypatch.setenv("GIT_REF", "main")
    bi.reset_cache()

    body = (await client.get("/api/system/version")).json()
    assert body["known"] is True
    assert body["pinned"] is False
    assert body["ref"] == "main"
