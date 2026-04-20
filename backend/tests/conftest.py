"""Shared fixtures for Sentinel-Next tests."""

from __future__ import annotations

import asyncio
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://pavelgalante@localhost:5432/sentinel")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-32ch")
os.environ.setdefault("DEMO_MODE", "false")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-fake")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from sentinel.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def superadmin_token(client: AsyncClient) -> str:
    resp = await client.post("/auth/login", json={
        "email": "admin@sentinel.ai",
        "password": "admin",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def auth_headers(superadmin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {superadmin_token}"}
