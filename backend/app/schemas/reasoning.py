import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class BaseSchema(BaseModel):
    model_config = {
        "from_attributes": True
    }


class LegalQARequest(BaseModel):
    question: str = Field(..., min_length=1)
    case_id: Optional[uuid.UUID] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    top_k: int = Field(5, ge=1, le=20)
    threshold: float = Field(0.0, ge=0.0, le=1.0)
    stream: bool = False


class LegalQAResponse(BaseSchema):
    id: uuid.UUID
    question: str
    answer: str
    intent: Optional[str] = None
    strategy: Optional[str] = None
    confidence: float
    confidence_breakdown: Optional[Dict[str, Any]] = None
    reasoning_steps: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    validation: Optional[Dict[str, Any]] = None
    contradictions: List[Dict[str, Any]] = []
    evidence_rankings: List[Dict[str, Any]] = []
    latency_ms: Optional[float] = None
    created_at: datetime


class QueryClassificationResponse(BaseModel):
    query: str
    intent: str
    strategy: str
    confidence: float
    reasoning_needed: bool


class EvidenceItem(BaseModel):
    id: str
    type: str  # "chunk", "entity", "event", "summary"
    description: str
    source: str
    score: float
    explanation: str


class EvidenceRankingResponse(BaseModel):
    query: str
    rankings: List[EvidenceItem]


class CitationItem(BaseModel):
    id: str
    text: str
    source_doc: str
    relevance_score: float
    strength: str  # "Primary", "Supporting", "Contextual"


class CitationRankingResponse(BaseModel):
    citations: List[CitationItem]


class ContradictionItem(BaseModel):
    id: str
    summary: str
    severity: str  # "low", "medium", "high"
    confidence: float
    evidence_ids: List[str]
    suggested_review: str


class ContradictionReportResponse(BaseSchema):
    id: uuid.UUID
    case_id: uuid.UUID
    summary: str
    severity: str
    confidence: float
    contradictions: List[ContradictionItem]
    created_at: datetime


class ComparisonRequest(BaseModel):
    case_id: uuid.UUID
    target_type: str  # "document", "case", "entity", "statute", "evidence"
    item_ids: List[uuid.UUID]


class ComparisonResponse(BaseModel):
    similarity_score: float
    comparison_table: List[Dict[str, Any]]
    narrative_summary: str


class ResearchSessionCreate(BaseModel):
    title: str = Field("New Research Session", max_length=255)
    case_id: Optional[uuid.UUID] = None


class ResearchNoteCreate(BaseModel):
    title: str = Field("Untitled Note", max_length=255)
    content: str = ""


class ResearchNoteResponse(BaseSchema):
    id: uuid.UUID
    session_id: uuid.UUID
    title: str
    content: str
    created_at: datetime
    updated_at: datetime


class ResearchSessionResponse(BaseSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    case_id: Optional[uuid.UUID] = None
    title: str
    bookmarks: Optional[List[Dict[str, Any]]] = None
    search_history: Optional[List[str]] = None
    notes: List[ResearchNoteResponse] = []
    created_at: datetime
    updated_at: datetime


class QAAnalyticsResponse(BaseModel):
    total_queries: int
    average_latency_ms: float
    average_confidence: float
    hallucination_rate: float
    intent_distribution: Dict[str, int]
    strategy_distribution: Dict[str, int]
    validation_failures: int
    evidence_utilization: float
    confidence_distribution: List[Dict[str, Any]]
