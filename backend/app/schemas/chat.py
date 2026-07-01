from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field

class BaseSchema(BaseModel):
    model_config = {
        "from_attributes": True
    }


class ChatMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    session_id: Optional[UUID] = None
    case_id: Optional[UUID] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    top_k: int = Field(5, ge=1, le=20)
    threshold: float = Field(0.0, ge=0.0, le=1.0)


class ChatMessageResponse(BaseSchema):
    id: UUID
    session_id: UUID
    role: str
    content: str
    citations_json: Optional[str] = None
    token_usage_json: Optional[str] = None
    latency_ms: Optional[float] = None
    created_at: datetime


class ChatSessionResponse(BaseSchema):
    id: UUID
    title: str
    case_id: Optional[UUID] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ChatQueryResponse(BaseModel):
    session_id: UUID
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse


class ChatHistoryResponse(BaseModel):
    sessions: List[ChatSessionResponse]
    total: int


class LLMProviderResponse(BaseModel):
    name: str
    label: str
    active: bool


class LLMModelResponse(BaseModel):
    provider: str
    name: str
    label: str


class RAGStatsResponse(BaseModel):
    total_chats: int
    average_latency_ms: float
    total_tokens_used: int
    total_estimated_cost: float
    provider_usage: Dict[str, int]


class LLMHealthResponse(BaseModel):
    status: str
    details: Dict[str, Any]


# ── Conversational Extensions (Phase 7.2) ──────────────────────────────────

class QueryRewriteRequest(BaseModel):
    query: str
    history: List[Dict[str, str]]


class QueryRewriteResponse(BaseModel):
    rewritten_query: str


class FollowupRequest(BaseModel):
    query: str
    history: List[Dict[str, str]]


class FollowupResponse(BaseModel):
    resolved_query: str


class ContextCompressRequest(BaseModel):
    chunks: List[Dict[str, Any]]
    max_tokens: int = 3000


class ContextCompressResponse(BaseModel):
    compressed_chunks: List[Dict[str, Any]]


class ProviderSelectRequest(BaseModel):
    query: str
    provider_override: Optional[str] = None


class ProviderSelectResponse(BaseModel):
    provider: str
    model: str


class PromptTemplateCreate(BaseModel):
    name: str
    version: str
    content: str
    description: Optional[str] = None


class PromptTemplateResponse(BaseSchema):
    id: UUID
    name: str
    version: str
    content: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ConversationMemoryResponse(BaseModel):
    session_id: str
    summary: str
    referenced_documents: List[Dict[str, Any]]
    referenced_entities: List[str]
    turn_count: int


class ConversationAnalyticsResponse(BaseModel):
    session_id: str
    average_latency_ms: float
    total_tokens: int
    estimated_cost: float
    turn_count: int


class GuardrailConfigResponse(BaseModel):
    status: str
    rules: List[str]
