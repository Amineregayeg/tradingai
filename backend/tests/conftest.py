"""Pytest configuration and shared fixtures for Trading AI Co-Pilot tests."""
import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Set DATABASE_URL to SQLite before any app module is imported.
# app/db/__init__.py eagerly creates an asyncpg engine at import time when
# the default PostgreSQL URL is present — using SQLite avoids that requirement
# for the test suite.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.config import Settings
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app

# ---------------------------------------------------------------------------
# Test settings override — use SQLite in-memory for unit tests
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Return a Settings instance with test-safe overrides."""
    return Settings(
        secret_key="test-secret-key-32-bytes-padded!!",
        database_url=TEST_DATABASE_URL,
        redis_url="redis://localhost:6379/15",
        oanda_api_key="test-oanda-key",
        oanda_account_id="test-account",
        oanda_environment="practice",
        anthropic_api_key="test-anthropic-key",
        ai_monthly_budget_usd=5.0,
        log_level="WARNING",
        data_dir="/tmp/tradingai_test",
    )


# ---------------------------------------------------------------------------
# In-memory SQLite async engine & session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def engine():
    """Create a fresh in-memory SQLite engine per test function.

    PostgreSQL-specific column types (JSONB, custom ENUMs) cannot be compiled
    by SQLite's DDL engine.  We register a before_cursor_execute event that
    patches JSONB → TEXT in the rendered DDL at the string level so table
    creation succeeds in SQLite without modifying the ORM metadata.

    Integration tests that require JSONB semantics or PG-specific features
    should be run against a real PostgreSQL instance
    (override DATABASE_URL in the environment).
    """
    import app.models  # ensure all ORM models are registered in Base.metadata  # noqa: F401
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy import JSON

    # Temporarily swap JSONB → JSON on all ORM columns so SQLite DDL compiles
    _patched: list[tuple[Any, Any]] = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, JSONB):
                _patched.append((col, col.type))
                col.type = JSON()

    test_engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)

    # Restore JSONB types on ORM columns so PG tests are unaffected
    for col, original_type in _patched:
        col.type = original_type

    try:
        yield test_engine
    finally:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await test_engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session bound to the test engine."""
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Test HTTP client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Return an async test client with the DB session dependency overridden."""
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    # Override get_db (the actual FastAPI dependency used in routers via DBSession)
    # and also get_session as a fallback for any direct Depends(get_session) usage.
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_anthropic_client() -> AsyncMock:
    """Return a mock Anthropic API client."""
    client = AsyncMock()
    client.messages.create = AsyncMock(
        return_value=AsyncMock(
            content=[AsyncMock(text='{"trend": "bullish", "confidence": 0.85}')],
            usage=AsyncMock(input_tokens=100, output_tokens=50),
            model="claude-sonnet-4-6",
        )
    )
    return client


# ---------------------------------------------------------------------------
# Wave 3 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def redis_mock():
    """Return a fakeredis instance (drop-in async Redis replacement)."""
    try:
        import fakeredis.aioredis as fakeredis_async

        return fakeredis_async.FakeRedis(decode_responses=True)
    except ImportError:
        # If fakeredis not installed, return a simple AsyncMock
        r = AsyncMock()
        r.get = AsyncMock(return_value=None)
        r.set = AsyncMock(return_value=True)
        r.setex = AsyncMock(return_value=True)
        r.delete = AsyncMock(return_value=1)
        r.exists = AsyncMock(return_value=0)
        r.aclose = AsyncMock(return_value=None)
        return r


@pytest.fixture
def broker_mock():
    """Return a mock BrokerAdapter."""
    from app.services.broker.base import BrokerAdapter

    adapter = AsyncMock(spec=BrokerAdapter)
    adapter.broker_name = "mock_broker"
    adapter.connect = AsyncMock(return_value=None)
    adapter.disconnect = AsyncMock(return_value=None)
    adapter.get_positions = AsyncMock(return_value=[])
    adapter.close_all_positions = AsyncMock(return_value=[])
    adapter.stream_prices = AsyncMock(return_value=None)
    return adapter


@pytest.fixture
def ai_mock():
    """Return a mock for the Anthropic client used by AIService."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(
        return_value=MagicMock(
            content=[MagicMock(text='{"analysis": "bullish setup", "confidence": 0.80}')],
            usage=MagicMock(input_tokens=150, output_tokens=75),
            model="claude-sonnet-4-6",
        )
    )
    return client


@pytest.fixture
def sample_trade_data() -> dict[str, Any]:
    """Return minimal data for creating a trade record."""
    return {
        "broker_id": "OANDA-123456",
        "broker": "oanda",
        "pair": "EUR_USD",
        "direction": "LONG",
        "entry_price": "1.085000",
        "lot_size": "0.100000",
        "entry_time": "2026-01-15T09:30:00+00:00",
    }


@pytest.fixture
def sample_alert_data() -> dict[str, Any]:
    """Return minimal data for creating an alert record."""
    return {
        "type": "ENTRY_SIGNAL",
        "priority": "SUGGESTION",
        "pair": "EUR_USD",
        "message": "Bullish OB detected at 1.0840 — consider long entry",
        "context_json": {"pair": "EUR_USD", "timeframe": "H1"},
        "expires_at": "2026-01-15T10:00:00+00:00",
    }
