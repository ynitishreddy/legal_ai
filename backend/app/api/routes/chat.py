from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query

from app.schemas import ChatHistoryResponse, ChatMessageRequest, ChatQueryResponse, ChatSessionResponse
from app.services.mock_data import MockDataService

router = APIRouter(prefix="/chat", tags=["Legal Chat"])


@router.get("/sessions", response_model=ChatHistoryResponse, summary="List chat sessions")
async def list_sessions() -> ChatHistoryResponse:
    return MockDataService.get_chat_sessions()


@router.post("/sessions", response_model=ChatSessionResponse, summary="Create a new chat session")
async def create_session(case_id: Optional[UUID] = None) -> ChatSessionResponse:
    from datetime import datetime, timezone
    from uuid import uuid4

    now = datetime.now(timezone.utc)
    return ChatSessionResponse(
        id=uuid4(),
        title="New Chat",
        case_id=case_id,
        is_active=True,
        created_at=now,
        updated_at=now,
        message_count=0,
    )


@router.post("/query", response_model=ChatQueryResponse, summary="Send a legal question")
async def send_query(payload: ChatMessageRequest) -> ChatQueryResponse:
    return MockDataService.send_chat_message(content=payload.content, session_id=payload.session_id)


@router.get("/sessions/{session_id}/messages", summary="Get messages for a session")
async def get_session_messages(session_id: UUID) -> dict:
    return {"session_id": str(session_id), "messages": [], "total": 0}
