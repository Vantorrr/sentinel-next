"""Admin API tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_admin_stats(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/admin/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_tenants" in data
    assert "total_users" in data


@pytest.mark.asyncio
async def test_admin_list_tenants(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/admin/tenants", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_admin_create_and_delete_tenant(client: AsyncClient, auth_headers: dict):
    import uuid
    slug = f"test-{uuid.uuid4().hex[:8]}"

    create_resp = await client.post("/admin/tenants", headers=auth_headers, json={
        "name": "Test Salon",
        "slug": slug,
        "plan": "free",
        "max_cameras": 2,
    })
    assert create_resp.status_code == 201
    tenant_id = create_resp.json()["id"]
    assert create_resp.json()["api_key"].startswith("sk-")

    del_resp = await client.delete(f"/admin/tenants/{tenant_id}", headers=auth_headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] == tenant_id


@pytest.mark.asyncio
async def test_admin_requires_auth(client: AsyncClient):
    resp = await client.get("/admin/stats")
    assert resp.status_code == 401
