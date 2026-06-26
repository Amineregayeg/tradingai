"""Smoke tests — verify the app can be imported and basic endpoints work."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """GET /api/system/health should return 200 and status=ok."""
    response = await client.get("/api/system/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_openapi_schema(client: AsyncClient) -> None:
    """GET /api/openapi.json should return a valid OpenAPI schema."""
    response = await client.get("/api/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Trading AI Co-Pilot"
    assert "paths" in schema


@pytest.mark.asyncio
async def test_system_info(client: AsyncClient) -> None:
    """GET /api/system/info should return non-sensitive config."""
    response = await client.get("/api/system/info")
    assert response.status_code == 200
    data = response.json()
    assert "ai_primary_model" in data
    # Ensure secrets are not leaked
    assert "anthropic_api_key" not in data
    assert "secret_key" not in data
