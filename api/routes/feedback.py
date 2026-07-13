"""
POST /api/feedback — rate a query result and trigger ChromaDB re-index
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from core.feedback import FeedbackManager, QueryRecord

router = APIRouter()


class FeedbackRequest(BaseModel):
    question: str
    sql: str
    tables: list[str]
    model_used: str
    rating: int = Field(..., ge=1, le=5)
    correction: str = ""    # user-provided corrected SQL (if rating <= 2)
    chat_id: str = "default"


class FeedbackResponse(BaseModel):
    accepted: bool
    added_to_index: bool
    message: str


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(body: FeedbackRequest, request: Request):
    """
    Accept a query rating from the user.
    High-rated queries (>= 4) are added to ChromaDB as few-shot examples.
    Corrected SQL (rating <= 2 with correction) replaces the original.
    """
    feedback_mgr: FeedbackManager = request.app.state.feedback_mgr

    record = QueryRecord(
        question=body.question,
        sql=body.sql,
        tables=body.tables,
        model_used=body.model_used,
        rating=body.rating,
        correction=body.correction,
        chat_id=body.chat_id,
    )

    feedback_mgr.record(record)

    added_to_index = body.rating >= 4
    msg = (
        "Added to example index — future similar queries will improve."
        if added_to_index
        else "Recorded. Thanks for the feedback."
    )

    return FeedbackResponse(
        accepted=True,
        added_to_index=added_to_index,
        message=msg,
    )
