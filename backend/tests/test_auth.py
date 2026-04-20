"""Authentication tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_superadmin(client: AsyncClient):
    resp = await client.post("/auth/login", json={
        "email": "admin@sentinel.ai",
        "password": "admin",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["role"] == "superadmin"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    resp = await client.post("/auth/login", json={
        "email": "admin@sentinel.ai",
        "password": "wrongpassword",
    })
    assert resp.status_code in (401, 400)


@pytest.mark.asyncio
async def test_protected_route_without_token(client: AsyncClient):
    resp = await client.get("/api/v1/cameras/")
    assert resp.status_code == 401
