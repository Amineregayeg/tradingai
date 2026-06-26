"""Tests that the app starts and health endpoint responds."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    response = await client.get("/api/system/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_openapi_schema_loads(client: AsyncClient):
    response = await client.get("/api/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "paths" in schema
    assert "/api/alerts/{alert_id}" in schema["paths"]


@pytest.mark.asyncio
async def test_list_alerts_empty(client: AsyncClient):
    response = await client.get("/api/alerts")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_positions_empty(client: AsyncClient):
    response = await client.get("/api/positions")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_settings(client: AsyncClient):
    response = await client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert "ai_enabled" in data
    assert "theme" in data
