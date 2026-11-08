"""Integration checks against an explicitly selected disposable PostgreSQL DB."""
import asyncio
import os
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

DB_URL = os.getenv('EDGE_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DB_URL, reason='Set EDGE_TEST_DATABASE_URL to isolated migrated PostgreSQL')

def test_durable_contract_and_isolation():
    async def run():
        from sentinel.api.routes.agent import router
        from sentinel.core.auth import get_current_tenant, TenantContext
        from sentinel.db.base import get_db
        from sentinel.db.models.edge_event import EdgeEventRecord
        from sentinel.services.analytics.edge_inbox import dispatch_once
        engine=create_async_engine(DB_URL)
        sessions=async_sessionmaker(engine,expire_on_commit=False)
        app=FastAPI();app.include_router(router,prefix='/api/v1')
        tenant_id=str(uuid4())
        async def db():
            async with sessions() as s: yield s
        principal=TenantContext(tenant_id,'admin')
        app.dependency_overrides[get_db]=db
        app.dependency_overrides[get_current_tenant]=lambda:principal
        payload={'agent_id':'test-agent','events':[{'type':'person.detected','camera_id':'test',
            'timestamp_ms':1700000000000,'payload':{'edge_event_id':str(uuid4())}}]}
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
                r=await c.post('/api/v1/agent/events',json=payload)
                assert r.status_code==200, r.text
                assert r.json()['durable'] is True
                assert r.json()['event_ids']==[payload['events'][0]['payload']['edge_event_id']]
                # Actual committed row is visible to a separate connection before caller drops queue.
                async with sessions() as s:
                    assert await s.scalar(select(func.count()).select_from(EdgeEventRecord).where(EdgeEventRecord.tenant_id==tenant_id))==1
                responses=await asyncio.gather(*[c.post('/api/v1/agent/events',json=payload) for _ in range(5)])
                assert all(x.status_code==200 for x in responses)
                assert len((await c.get('/api/v1/agent/events')).json()['events'])==1
                # Same key with changed body rejected, original remains unchanged.
                payload['events'][0]['camera_id']='changed'
                assert (await c.post('/api/v1/agent/events',json=payload)).status_code==422
                payload['events'][0]['camera_id']='test'
                assert (await c.get('/api/v1/agent/events')).json()['events'][0]['camera_id']=='test'
                principal=TenantContext(str(uuid4()),'admin')
                assert (await c.get('/api/v1/agent/events')).json()['events']==[]
                assert (await c.post('/api/v1/agent/events',json=payload)).status_code==200
                assert len((await c.get('/api/v1/agent/events')).json()['events'])==1
            bus=AsyncMock();bus.publish.side_effect=RuntimeError('offline')
            with pytest.raises(RuntimeError):await dispatch_once(sessions,bus)
            async with sessions() as s:
                assert await s.scalar(select(func.count()).select_from(EdgeEventRecord).where(EdgeEventRecord.published_at.is_(None)))>=2
            bus.publish.side_effect=None
            assert await dispatch_once(sessions,bus)>=2
            assert await dispatch_once(sessions,bus)==0
        finally:
            await engine.dispose()
    asyncio.run(run())

def test_transaction_failure_has_no_receipt():
    async def run():
        from sentinel.services.analytics.edge_inbox import store_batch
        from sentinel.api.routes.agent import AgentEvent
        engine=create_async_engine(DB_URL);sessions=async_sessionmaker(engine)
        async with sessions() as db:
            db.commit=AsyncMock(side_effect=RuntimeError('commit failed'))
            with pytest.raises(RuntimeError):
                await store_batch(db,str(uuid4()),'a',[AgentEvent(type='person.detected',timestamp_ms=1,payload={'edge_event_id':str(uuid4())})])
            await db.rollback()
        await engine.dispose()
    asyncio.run(run())


def test_legacy_agents_remain_compatible():
    async def run():
        from sentinel.services.analytics.edge_inbox import store_batch
        from sentinel.api.routes.agent import AgentEvent
        from sentinel.db.models.edge_event import EdgeEventRecord
        engine=create_async_engine(DB_URL);sessions=async_sessionmaker(engine)
        tenant=str(uuid4())
        event=AgentEvent(type='person.detected',camera_id='legacy')
        async def send():
            async with sessions() as db:
                return await store_batch(db,tenant,'old-agent',[event])
        ids=await asyncio.gather(send(),send(),send())
        assert ids[0]==ids[1]==ids[2]
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(EdgeEventRecord).where(EdgeEventRecord.tenant_id==tenant))==1
        await engine.dispose()
    asyncio.run(run())
