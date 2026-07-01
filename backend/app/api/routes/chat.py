import logging
import uuid
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.api.deps import get_current_active_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models import User, ChatSession, ChatMessage, ChatRole
from app.schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionResponse,
    ChatQueryResponse,
    ChatHistoryResponse,
    LLMProviderResponse,
    LLMModelResponse,
    RAGStatsResponse,
    LLMHealthResponse,
    MessageResponse,
    QueryRewriteRequest,
    QueryRewriteResponse,
    FollowupRequest,
    FollowupResponse,
    ContextCompressRequest,
    ContextCompressResponse,
    ProviderSelectRequest,
    ProviderSelectResponse,
    PromptTemplateCreate,
    PromptTemplateResponse,
    ConversationMemoryResponse,
    ConversationAnalyticsResponse,
    GuardrailConfigResponse,
)
from app.services.rag import RAGService
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Legal Chat"])


# 1. POST /api/chat/message -> Send a message (single-turn RAG)
@router.post(
    "/message",
    response_model=ChatQueryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_chat_message(
    payload: ChatMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    session_id = payload.session_id or uuid.uuid4()
    service = RAGService(db)
    
    try:
        assistant_msg = service.query_rag(
            session_id=session_id,
            user_id=current_user.id,
            question=payload.content,
            provider=payload.provider,
            model=payload.model,
            top_k=payload.top_k,
            threshold=payload.threshold,
            case_id=payload.case_id,
        )
        
        # Load user query message for response
        user_msg = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.role == ChatRole.USER,
            )
            .order_by(desc(ChatMessage.created_at))
            .first()
        )

        return ChatQueryResponse(
            session_id=session_id,
            user_message=ChatMessageResponse.model_validate(user_msg),
            assistant_message=ChatMessageResponse.model_validate(assistant_msg),
        )
    except Exception as e:
        logger.error("send_chat_message: Failed: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate chat response: {str(e)}"
        )


# 2. POST /api/chat/stream -> Stream tokens using SSE
@router.post("/stream")
async def chat_stream_endpoint(
    payload: ChatMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    session_id = payload.session_id or uuid.uuid4()
    service = RAGService(db)
    
    def event_generator():
        try:
            stream_gen = service.stream_rag(
                session_id=session_id,
                user_id=current_user.id,
                question=payload.content,
                provider=payload.provider,
                model=payload.model,
                top_k=payload.top_k,
                threshold=payload.threshold,
                case_id=payload.case_id,
            )
            for event in stream_gen:
                yield f"event: {event['event']}\ndata: {event['data']}\n\n"
        except Exception as e:
            logger.error("chat_stream_endpoint: Streaming failed: %s", str(e))
            yield f"event: error\ndata: {str(e)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# 11. POST /api/chat/sessions -> Create a new session
@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    case_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    session = ChatSession(
        user_id=current_user.id,
        case_id=case_id,
        title="New Chat",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        case_id=session.case_id,
        is_active=session.is_active,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=0,
    )


# 3. GET /api/chat/sessions -> List sessions
@router.get(
    "/sessions",
    response_model=ChatHistoryResponse,
)
async def list_sessions(
    case_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = db.query(ChatSession).filter(ChatSession.user_id == current_user.id)
    if case_id:
        query = query.filter(ChatSession.case_id == case_id)
        
    query = query.order_by(desc(ChatSession.updated_at))
    
    total = query.count()
    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()
    
    # Resolve message_count for each session
    response_items = []
    for s in items:
        count = db.query(func.count(ChatMessage.id)).filter(ChatMessage.session_id == s.id).scalar() or 0
        response_items.append(
            ChatSessionResponse(
                id=s.id,
                title=s.title,
                case_id=s.case_id,
                is_active=s.is_active,
                created_at=s.created_at,
                updated_at=s.updated_at,
                message_count=count,
            )
        )

    return ChatHistoryResponse(
        sessions=response_items,
        total=total,
    )


# 4. GET /api/chat/sessions/{id} -> Single session view
@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionResponse,
)
async def get_session(
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chat session {session_id} not found."
        )
    
    count = db.query(func.count(ChatMessage.id)).filter(ChatMessage.session_id == session.id).scalar() or 0
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        case_id=session.case_id,
        is_active=session.is_active,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=count,
    )


# 5. GET /api/chat/messages/{session_id} -> Get messages
@router.get(
    "/messages/{session_id}",
    response_model=List[ChatMessageResponse],
)
async def get_messages(
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return messages


# 6. DELETE /api/chat/session/{id} -> Delete session
@router.delete(
    "/session/{session_id}",
    response_model=MessageResponse,
)
async def delete_session(
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found."
        )
    
    db.delete(session)
    db.commit()
    return MessageResponse(message="Session deleted successfully.", success=True)


# 7. GET /api/chat/providers -> Get supported providers
@router.get(
    "/providers",
    response_model=List[LLMProviderResponse],
)
async def get_providers(
    current_user: User = Depends(get_current_active_user),
):
    settings = get_settings()
    
    # Determine if API keys are set to evaluate active flag
    return [
        LLMProviderResponse(name="mock", label="Mock LLM Offline Fallback", active=True),
        LLMProviderResponse(name="openai", label="OpenAI API Gateway", active=bool(settings.openai_api_key)),
        LLMProviderResponse(name="gemini", label="Google Gemini Workspace", active=bool(settings.gemini_api_key)),
        LLMProviderResponse(name="ollama", label="Ollama Local Models (Llama3)", active=True),
    ]


# 8. GET /api/chat/models -> Get models list
@router.get(
    "/models",
    response_model=List[LLMModelResponse],
)
async def get_models(
    current_user: User = Depends(get_current_active_user),
):
    service = LLMService()
    models = service.list_models()
    return [LLMModelResponse(**m) for m in models]


# 9. GET /api/chat/health -> Health monitor
@router.get(
    "/health",
    response_model=LLMHealthResponse,
)
async def get_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = LLMService()
    
    openai_ok = service.health_check("openai")
    gemini_ok = service.health_check("gemini")
    ollama_ok = service.health_check("ollama")

    details = {
        "openai_gateway": "online" if openai_ok else "offline",
        "gemini_workspace": "online" if gemini_ok else "offline",
        "ollama_local": "online" if ollama_ok else "offline",
    }
    
    status_str = "healthy"
    if not (openai_ok or gemini_ok or ollama_ok):
        # Allow mock to keep health status healthy
        status_str = "healthy (mock-mode active)"

    return LLMHealthResponse(status=status_str, details=details)


# 10. GET /api/chat/statistics -> Cost and token tracking
@router.get(
    "/statistics",
    response_model=RAGStatsResponse,
)
async def get_statistics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = RAGService(db)
    try:
        stats_data = service.get_statistics(current_user.id)
        return RAGStatsResponse(**stats_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch stats: {str(e)}"
        )


# 12. POST /api/chat/rewrite -> Standalone query compiler
@router.post(
    "/rewrite",
    response_model=QueryRewriteResponse,
)
async def rewrite_query_endpoint(
    payload: QueryRewriteRequest,
    current_user: User = Depends(get_current_active_user),
):
    from app.services.query_rewrite import QueryRewriteService
    svc = QueryRewriteService()
    rewritten = svc.rewrite_query(payload.query, payload.history)
    return QueryRewriteResponse(rewritten_query=rewritten)


# 13. POST /api/chat/followup -> Pronoun resolution
@router.post(
    "/followup",
    response_model=FollowupResponse,
)
async def followup_query_endpoint(
    payload: FollowupRequest,
    current_user: User = Depends(get_current_active_user),
):
    from app.services.query_rewrite import QueryRewriteService
    svc = QueryRewriteService()
    resolved = svc.resolve_followup(payload.query, payload.history)
    return FollowupResponse(resolved_query=resolved)


# 14. POST /api/chat/context/compress -> Token pruner
@router.post(
    "/context/compress",
    response_model=ContextCompressResponse,
)
async def compress_context_endpoint(
    payload: ContextCompressRequest,
    current_user: User = Depends(get_current_active_user),
):
    from app.services.context_compression import ContextCompressionEngine
    svc = ContextCompressionEngine()
    compressed = svc.compress_chunks(payload.chunks, payload.max_tokens)
    return ContextCompressResponse(compressed_chunks=compressed)


# 15. POST /api/chat/provider/select -> Router decision
@router.post(
    "/provider/select",
    response_model=ProviderSelectResponse,
)
async def select_provider_endpoint(
    payload: ProviderSelectRequest,
    current_user: User = Depends(get_current_active_user),
):
    from app.services.provider_router import ProviderRoutingEngine
    svc = ProviderRoutingEngine()
    route = svc.select_route(payload.query, payload.provider_override)
    return ProviderSelectResponse(**route)


# 16. GET /api/chat/conversation/{id}/memory -> Inspector detail
@router.get(
    "/conversation/{session_id}/memory",
    response_model=ConversationMemoryResponse,
)
async def get_conversation_memory(
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.services.memory import ConversationMemoryService
    svc = ConversationMemoryService(db)
    mem = svc.get_conversation_context(session_id)
    return ConversationMemoryResponse(**mem)


# 17. GET /api/chat/conversation/{id}/analytics -> Turn depth & stats
@router.get(
    "/conversation/{session_id}/analytics",
    response_model=ConversationAnalyticsResponse,
)
async def get_conversation_analytics(
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # Sum up metrics for this session ID
    messages_count = db.query(func.count(ChatMessage.id)).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.role == ChatRole.ASSISTANT
    ).scalar() or 0

    avg_latency = db.query(func.avg(ChatMessage.latency_ms)).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.role == ChatRole.ASSISTANT
    ).scalar() or 0.0

    total_tokens = db.query(func.sum(ChatMessage.token_count)).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.role == ChatRole.ASSISTANT
    ).scalar() or 0

    usages = db.query(ChatMessage.token_usage_json).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.role == ChatRole.ASSISTANT
    ).all()

    total_cost = 0.0
    for (u_str,) in usages:
        if u_str:
            try:
                total_cost += json.loads(u_str).get("estimated_cost", 0.0)
            except Exception:
                pass

    return ConversationAnalyticsResponse(
        session_id=str(session_id),
        average_latency_ms=round(float(avg_latency), 2),
        total_tokens=int(total_tokens),
        estimated_cost=round(total_cost, 5),
        turn_count=messages_count,
    )


# 18. GET /api/chat/prompts -> List templates
@router.get(
    "/prompts",
    response_model=List[PromptTemplateResponse],
)
async def list_prompts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    templates = db.query(PromptTemplate).order_by(PromptTemplate.name, PromptTemplate.version.desc()).all()
    return templates


# 19. POST /api/chat/prompts -> Create template
@router.post(
    "/prompts",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt(
    payload: PromptTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # Set other templates of same name to inactive if needed, or maintain simple list
    tmpl = PromptTemplate(
        name=payload.name,
        version=payload.version,
        content=payload.content,
        description=payload.description,
        is_active=True,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return tmpl


# 20. PUT /api/chat/prompts/{id} -> Update / Activate prompt
@router.put(
    "/prompts/{prompt_id}",
    response_model=PromptTemplateResponse,
)
async def update_prompt(
    prompt_id: UUID,
    is_active: bool,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tmpl = db.get(PromptTemplate, prompt_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="PromptTemplate not found.")
        
    tmpl.is_active = is_active
    
    # If set to active, set all other templates with same name to inactive to ensure uniqueness
    if is_active:
        db.query(PromptTemplate).filter(
            PromptTemplate.name == tmpl.name,
            PromptTemplate.id != prompt_id
        ).update({"is_active": False})
        
    db.commit()
    db.refresh(tmpl)
    return tmpl


# 21. GET /api/chat/provider/statistics -> Cost details by provider
@router.get(
    "/provider/statistics",
)
async def get_provider_statistics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = RAGService(db)
    stats_data = service.get_statistics(current_user.id)
    return stats_data


# 22. GET /api/chat/guardrails -> Guardrails rules
@router.get(
    "/guardrails",
    response_model=GuardrailConfigResponse,
)
async def get_guardrails_config(
    current_user: User = Depends(get_current_active_user),
):
    return GuardrailConfigResponse(
        status="active",
        rules=[
            "Prompt Injection block signature: 'ignore previous instructions'",
            "System Prompt Leakage block signature: 'system instructions'",
            "Command Override block signature: 'overwrite instructions'",
        ]
    )
