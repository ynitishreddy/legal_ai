import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, ConfigDict


class SummaryCitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    citation_type: str
    source_id: Optional[uuid.UUID] = None
    source_title: str
    page_number: Optional[int] = None
    citation_text: Optional[str] = None
    created_at: datetime


class SummaryVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    summary_text: str
    provider: str
    model_used: str
    prompt_version: str
    confidence_score: float
    citation_coverage: float
    completeness_score: float
    token_usage_json: Optional[str] = None
    validation_status: str
    is_active: bool
    created_at: datetime
    citations: List[SummaryCitationResponse] = []


class SummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    summary_type: str
    created_at: datetime
    updated_at: datetime
    versions: List[SummaryVersionResponse] = []


class SummaryRequest(BaseModel):
    case_id: uuid.UUID
    summary_type: str
    provider: Optional[str] = None
    model: Optional[str] = None
    regenerate: bool = False


class SummaryCompareRequest(BaseModel):
    version_id_1: uuid.UUID
    version_id_2: uuid.UUID


class SummaryCompareResponse(BaseModel):
    version_1: SummaryVersionResponse
    version_2: SummaryVersionResponse
    diff_text: str


class SummaryGenerationJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    summary_type: str
    status: str
    progress: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
