"""
GET  /api/chat/history/{chat_id}  — load message history for a chat
GET  /api/chat/list               — list all chats (for sidebar)
POST /api/chat/close/{chat_id}    — archive active chat to MongoDB
POST /api/chat/resume/{chat_id}   — restore archived chat to Redis
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from core.memory.memory_manager import MemoryManager

router = APIRouter()


class ChatContext(BaseModel):
    chat_id: str
    summary: str
    messages: list[dict]


@router.get("/list")
async def list_chats(request: Request):
    memory_mgr: MemoryManager = request.app.state.memory_mgr
    return {"chats": memory_mgr.list_chats(limit=30)}


@router.get("/history/{chat_id}", response_model=ChatContext)
async def get_history(chat_id: str, request: Request):
    memory_mgr: MemoryManager = request.app.state.memory_mgr
    context = memory_mgr.get_context(chat_id)
    return ChatContext(
        chat_id=chat_id,
        summary=context["summary"],
        messages=context["messages"],
    )


@router.post("/close/{chat_id}")
async def close_chat(chat_id: str, request: Request):
    """Archive active Redis session to MongoDB. Called when user starts new chat."""
    memory_mgr: MemoryManager = request.app.state.memory_mgr
    memory_mgr.close_chat(chat_id)
    return {"status": "archived", "chat_id": chat_id}


@router.post("/resume/{chat_id}", response_model=ChatContext)
async def resume_chat(chat_id: str, request: Request):
    """Restore archived chat from MongoDB into Redis for fast access."""
    memory_mgr: MemoryManager = request.app.state.memory_mgr
    context = memory_mgr.resume_chat(chat_id)
    return ChatContext(
        chat_id=chat_id,
        summary=context["summary"],
        messages=context["messages"],
    )


@router.get("/health")
async def memory_health(request: Request):
    memory_mgr: MemoryManager = request.app.state.memory_mgr
    return memory_mgr.health()
