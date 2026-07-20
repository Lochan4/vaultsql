"""
GET /api/usage/* — token usage and cost visibility endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter

from core import token_counter

router = APIRouter()


@router.get("/summary")
async def usage_summary():
    """
    Aggregate totals across all recorded LLM calls.

    Returns total cost, token counts, and breakdowns by model and task type.
    """
    return token_counter.get_summary()


@router.get("/by-task")
async def usage_by_task():
    """
    Per-task-type breakdown: calls, input tokens, output tokens, total cost.

    Task types: anchor_extraction, joinability, sql_simple, sql_medium,
    sql_complex, synthesis, summarization, knowledge_extraction,
    reference_detection.
    """
    return {"tasks": token_counter.get_by_task()}


@router.get("/by-chat/{chat_id}")
async def usage_by_chat(chat_id: str):
    """
    All LLM calls made within a specific chat session, in chronological order.
    """
    return {"chat_id": chat_id, "calls": token_counter.get_by_chat(chat_id)}


@router.get("/recent")
async def usage_recent(limit: int = 50):
    """
    Most recent N LLM calls. Useful for debugging and live monitoring.
    """
    return {"calls": token_counter.get_recent(limit)}
