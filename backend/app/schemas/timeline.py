from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


class BaseSchema(BaseModel):
    model_config = {
        "from_attributes": True
    }


class TimelineExtractionRequest(BaseModel):
    case_id: UUID
    document_id: UUID


class TimelineRebuildRequest(BaseModel):
    case_id: UUID


class LegalEventResponse(BaseSchema):
    id: UUID
    case_id: UUID
    document_id: Optional[UUID] = None
    event_type: str
    event_title: str
    event_description: str
    normalized_date: Optional[datetime] = None
    original_date: str
    confidence_score: float
    page_number: Optional[int] = None
    chunk_id: Optional[str] = None
    source_text: Optional[str] = None
    linked_child_events: List[str] = []


class EventRelationshipResponse(BaseSchema):
    id: UUID
    parent_event_id: UUID
    child_event_id: UUID
    relationship_type: str


class TimelineStatsResponse(BaseModel):
    total_events: int
    category_breakdown: Dict[str, int]
    average_confidence: float
    timeline_span_days: int
