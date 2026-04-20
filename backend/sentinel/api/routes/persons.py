"""Person enrollment, listing, and management — tenant-scoped."""

from __future__ import annotations

import io
import uuid
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.core.auth import TenantContext, get_current_tenant
from sentinel.db.base import get_db
from sentinel.db.models.person import Person, PersonCategory
from sentinel.pipeline.manager import get_manager

router = APIRouter(prefix="/persons", tags=["persons"])


class PersonOut(BaseModel):
    id: str
    name: str
    category: str
    visit_count: int
    phone: str | None
    email: str | None
    notes: str | None

    model_config = {"from_attributes": True}


@router.post("/enroll", status_code=status.HTTP_201_CREATED)
async def enroll_person(
    name: Annotated[str, Form()],
    category: Annotated[PersonCategory, Form()] = PersonCategory.REGULAR,
    phone: Annotated[str | None, Form()] = None,
    email: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    photo: UploadFile = File(...),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if tenant.tenant_id == "__all__":
        raise HTTPException(400, "Superadmin cannot enroll persons — switch to a tenant context")
    content = await photo.read()
    pil_img = Image.open(io.BytesIO(content)).convert("RGB")
    image_np = np.array(pil_img)[:, :, ::-1].copy()

    manager = get_manager()
    if manager._reid is None:
        raise HTTPException(status_code=503, detail="ReID service not ready")

    embedding = await manager._reid.get_embedding_for_face(image_np)
    if embedding is None:
        raise HTTPException(status_code=400, detail="No face detected in photo")

    person_id = str(uuid.uuid4())

    await manager._reid.register(
        person_id=person_id,
        name=name,
        category=category.value,
        embedding=embedding,
    )

    person = Person(
        id=person_id,
        tenant_id=tenant.tenant_id,
        name=name,
        category=category,
        phone=phone,
        email=email,
        notes=notes,
    )
    db.add(person)
    await db.commit()

    return {"person_id": person_id, "name": name, "category": category}


@router.get("/", response_model=list[PersonOut])
async def list_persons(
    category: PersonCategory | None = None,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[PersonOut]:
    stmt = select(Person)
    if tenant.tenant_id != "__all__":
        stmt = stmt.where(Person.tenant_id == tenant.tenant_id)
    if category:
        stmt = stmt.where(Person.category == category)
    stmt = stmt.order_by(Person.last_seen.desc()).limit(200)
    rows = (await db.execute(stmt)).scalars().all()
    return [PersonOut.model_validate(p) for p in rows]


@router.get("/{person_id}", response_model=PersonOut)
async def get_person(
    person_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> PersonOut:
    stmt = select(Person).where(Person.id == person_id)
    if tenant.tenant_id != "__all__":
        stmt = stmt.where(Person.tenant_id == tenant.tenant_id)
    p = (await db.execute(stmt)).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    return PersonOut.model_validate(p)
