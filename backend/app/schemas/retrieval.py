from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field

class BaseSchema(BaseModel):
    model_config = {
        "from_attributes": True
    }


class RetrievalSearchRequest(BaseModel):
    query_text: str = Field(..., min_length=1, description="Natural language search term")
    case_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    document_type: Optional[str] = None
    filename: Optional[str] = None
    tags: Optional[List[str]] = None
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    top_k: int = Field(5, ge=1, le=50)
    score_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)


class RetrievalChunkResponse(BaseSchema):
    chunk_id: UUID
    document_id: UUID
    document_name: str
    case_id: str
    page_number: int
    section_title: str
    similarity_score: float
    embedding_version: str
    source_path: str
    text: str
    chunk_index: int


class ContextWindowRequest(BaseModel):
    chunks: List[Dict[str, Any]] = Field(..., description="Ranked citation list returned from search")
    max_tokens: int = Field(4000, ge=500, le=32000)


class ContextWindowResponse(BaseModel):
    context_text: str
    total_chunks_merged: int


class RetrievalLogResponse(BaseSchema):
    id: UUID
    query_text: str
    filters_json: Optional[str] = None
    retrieved_documents_json: Optional[str] = None
    latency_ms: float
    top_score: float
    chunks_returned: int
    created_at: datetime


class RetrievalLogListResponse(BaseModel):
    items: List[RetrievalLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class RetrievalStatsResponse(BaseModel):
    total_requests: int
    average_latency_ms: float
    average_similarity_score: float
    cache_hit_ratio: float
    failed_requests: int
    top_retrieved_documents: List[Dict[str, Any]]


class RetrievalHealthResponse(BaseModel):
    status: str
    active_queries_count: int
    embedding_cache_size: int
    retrieval_cache_size: int


class ChunkPreviewRequest(BaseModel):
    chunk_id: UUID

