"""AI Chat Assistant endpoint — tenant-scoped."""

from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.core.auth import TenantContext, get_current_tenant, require_ws_auth
from sentinel.db.base import get_db
from sentinel.services.llm.chat_assistant import ChatAssistant

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    history: list[dict] = []


class ChatResponse(BaseModel):
    answer: str


@router.post("/", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    assistant = ChatAssistant(db, tenant_id=tenant.tenant_id)
    answer = await assistant.ask(req.question, req.history)
    return ChatResponse(answer=answer)


@router.websocket("/ws")
async def chat_ws(
    websocket: WebSocket,
    tenant: TenantContext = Depends(require_ws_auth),
    db: AsyncSession = Depends(get_db),
) -> None:
    await websocket.accept()
    assistant = ChatAssistant(db, tenant_id=tenant.tenant_id)
    history: list[dict] = []

    try:
        while True:
            data = await websocket.receive_json()
            question = data.get("question", "")
            if not question:
                continue

            answer = await assistant.ask(question, history)
            history.append({"role": "user", "content": question})
            history.append({"role": "assistant", "content": answer})

            if len(history) > 20:
                history = history[-20:]

            await websocket.send_json({"answer": answer, "done": True})
    except WebSocketDisconnect:
        pass
