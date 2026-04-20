"""Camera API tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_cameras_list_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/cameras/")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cameras_list_ok(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/cameras/", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_superadmin_cannot_add_camera(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/v1/cameras/", headers=auth_headers, json={
        "id": "test-cam",
        "url": "rtsp://fake",
        "name": "Test",
    })
    assert resp.status_code == 400
    assert "Superadmin" in resp.json()["detail"]
