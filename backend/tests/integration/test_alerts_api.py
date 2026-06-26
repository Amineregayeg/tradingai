"""Integration tests for the alerts API endpoints.

Requires: the `client` fixture from conftest.py (in-memory SQLite DB + ASGI app).

All tests in this module are marked with @pytest.mark.integration.
They do NOT require Docker — the in-memory SQLite engine is sufficient for
endpoint-level validation.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# GET /api/alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_alerts_returns_200_and_list(client: AsyncClient) -> None:
    response = await client.get("/api/alerts")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_list_alerts_empty_db_returns_empty_list(client: AsyncClient) -> None:
    response = await client.get("/api/alerts")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_alerts_invalid_status_returns_422(client: AsyncClient) -> None:
    response = await client.get("/api/alerts?status=INVALID")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_alerts_invalid_priority_returns_422(client: AsyncClient) -> None:
    response = await client.get("/api/alerts?priority=NOT_A_PRIORITY")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_alerts_valid_status_filter(client: AsyncClient) -> None:
    """A valid status query param should not cause an error on an empty DB."""
    response = await client.get("/api/alerts?status=PENDING")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_alerts_valid_priority_filter(client: AsyncClient) -> None:
    response = await client.get("/api/alerts?priority=WARNING")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_list_alerts_pagination_params_accepted(client: AsyncClient) -> None:
    response = await client.get("/api/alerts?page=2&page_size=10")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_alerts_page_size_too_large_rejected(client: AsyncClient) -> None:
    """page_size > 500 should be rejected (FastAPI validation)."""
    response = await client.get("/api/alerts?page_size=9999")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_alerts_page_zero_rejected(client: AsyncClient) -> None:
    """page=0 violates ge=1 constraint."""
    response = await client.get("/api/alerts?page=0")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/alerts/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_nonexistent_alert_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/alerts/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_alert_invalid_uuid_returns_422(client: AsyncClient) -> None:
    response = await client.get("/api/alerts/not-a-uuid")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/alerts/{id}  (governance actions)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_act_on_nonexistent_alert_returns_404(client: AsyncClient) -> None:
    response = await client.patch(
        f"/api/alerts/{uuid.uuid4()}",
        json={"action": "approve"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_act_with_invalid_uuid_returns_422(client: AsyncClient) -> None:
    response = await client.patch(
        "/api/alerts/bad-uuid",
        json={"action": "approve"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_act_missing_action_returns_422(client: AsyncClient) -> None:
    """Payload without the required 'action' field should fail validation."""
    response = await client.patch(
        f"/api/alerts/{uuid.uuid4()}",
        json={"reason": "no action provided"},
    )
    assert response.status_code == 422
