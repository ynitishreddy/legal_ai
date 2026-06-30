from datetime import datetime
from typing import Generic, List, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class MessageResponse(BaseModel):
    message: str
    success: bool = True


# ── Auth ──────────────────────────────────────────────────────────────────────

class UserRegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=255)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenRefreshRequest(BaseModel):
    refresh_token: str


# ── User ──────────────────────────────────────────────────────────────────────

class UserResponse(BaseSchema):
    id: UUID
    email: str
    username: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    is_verified: bool
    avatar_url: Optional[str] = None
    created_at: datetime


class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    avatar_url: Optional[str] = Field(None, max_length=500)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardStatsResponse(BaseModel):
    totalCases: int = 0
    totalDocuments: int = 0
    activeCases: int = 0
    closedCases: int = 0
    archivedCases: int = 0
    timelineEvents: int = 0
    # Phase 5.1 — Processing stats
    processingQueued: int = 0
    processingRunning: int = 0
    processingCompletedToday: int = 0
    processingFailed: int = 0


# ── Cases ─────────────────────────────────────────────────────────────────────

class CaseCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    case_number: Optional[str] = Field(None, max_length=100)
    court_name: Optional[str] = Field(None, max_length=255)
    jurisdiction: Optional[str] = Field(None, max_length=255)
    judge_name: Optional[str] = Field(None, max_length=255)
    client_name: Optional[str] = Field(None, max_length=255)
    opposing_party: Optional[str] = Field(None, max_length=255)
    status: str = Field("open")
    priority: str = Field("medium")
    tags: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=10000)


class CaseUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    case_number: Optional[str] = Field(None, max_length=100)
    court_name: Optional[str] = Field(None, max_length=255)
    jurisdiction: Optional[str] = Field(None, max_length=255)
    judge_name: Optional[str] = Field(None, max_length=255)
    client_name: Optional[str] = Field(None, max_length=255)
    opposing_party: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=10000)


class CaseResponse(BaseSchema):
    id: UUID
    title: str
    description: Optional[str] = None
    case_number: Optional[str] = None
    court_name: Optional[str] = None
    jurisdiction: Optional[str] = None
    judge_name: Optional[str] = None
    client_name: Optional[str] = None
    opposing_party: Optional[str] = None
    status: str
    priority: str
    tags: Optional[str] = None
    notes: Optional[str] = None
    archived: bool
    owner_id: UUID
    created_at: datetime
    updated_at: datetime




# ── Document ──────────────────────────────────────────────────────────────────

class DocumentResponse(BaseSchema):
    id: UUID
    title: str
    filename: str
    file_size: int
    mime_type: Optional[str] = None
    document_type: str
    status: str
    page_count: Optional[int] = None
    case_id: Optional[UUID] = None
    original_filename: Optional[str] = None
    stored_filename: Optional[str] = None
    storage_path: Optional[str] = None
    file_extension: Optional[str] = None
    checksum: Optional[str] = None
    upload_status: str
    processing_status: str
    
    # Phase 4.3 additions
    document_category: str
    user_tags: List[str] = []
    description: Optional[str] = None
    last_accessed_at: Optional[datetime] = None
    is_favorite: bool = False
    
    created_at: datetime
    updated_at: datetime

    @field_validator("user_tags", mode="before")
    @classmethod
    def parse_user_tags(cls, v):
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        if isinstance(v, list):
            return v
        return []


class DocumentUpdateRequest(BaseModel):
    tags: Optional[List[str]] = None
    description: Optional[str] = Field(None, max_length=1000)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        cleaned_tags = []
        seen = set()
        for tag in v:
            stripped = tag.strip()
            if not stripped:
                raise ValueError("Tags cannot be empty strings")
            if len(stripped) > 50:
                raise ValueError("Individual tag length cannot exceed 50 characters")
            if stripped.lower() in seen:
                continue
            seen.add(stripped.lower())
            cleaned_tags.append(stripped)
        return cleaned_tags


class DocumentUploadResponse(BaseModel):
    id: UUID
    title: str
    filename: str
    status: str
    message: str


class DocumentFilterParams(BaseModel):
    search: Optional[str] = None
    status: Optional[str] = None
    document_type: Optional[str] = None
    case_id: Optional[UUID] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(10, ge=1, le=100)




# ── Timeline ──────────────────────────────────────────────────────────────────

class TimelineEventResponse(BaseSchema):
    id: UUID
    title: str
    description: Optional[str] = None
    event_date: datetime
    event_type: Optional[str] = None
    confidence_score: Optional[float] = None
    case_id: UUID
    document_id: Optional[UUID] = None


class TimelineResponse(BaseModel):
    events: List[TimelineEventResponse]
    total: int
    case_id: Optional[UUID] = None


class TimelineFilterParams(BaseModel):
    case_id: Optional[UUID] = None
    event_type: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    session_id: Optional[UUID] = None
    case_id: Optional[UUID] = None


class ChatMessageResponse(BaseSchema):
    id: UUID
    content: str
    role: str
    session_id: UUID
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


# ── Analytics ─────────────────────────────────────────────────────────────────

class AnalyticsMetricResponse(BaseModel):
    name: str
    value: float
    unit: Optional[str] = None
    change_percent: Optional[float] = None
    trend: Optional[str] = None


class AnalyticsChartDataPoint(BaseModel):
    label: str
    value: float


class AnalyticsChartResponse(BaseModel):
    title: str
    chart_type: str
    data: List[AnalyticsChartDataPoint]


class AnalyticsOverviewResponse(BaseModel):
    metrics: List[AnalyticsMetricResponse]
    charts: List[AnalyticsChartResponse]
    summary: dict


class AnalyticsFilterParams(BaseModel):
    case_id: Optional[UUID] = None
    category: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


# ── Bulk Document Operations ──────────────────────────────────────────────────

class BulkDeleteRequest(BaseModel):
    document_ids: List[UUID]


class BulkDeleteResponse(BaseModel):
    deleted_count: int
    skipped_count: int
    failures: List[str]


class BulkDownloadRequest(BaseModel):
    document_ids: List[UUID]


class BulkMoveRequest(BaseModel):
    document_ids: List[UUID]
    destination_case_id: UUID


class BulkMoveResponse(BaseModel):
    moved_count: int
    skipped_count: int
    failures: List[str]


# ── Processing Jobs (Phase 5.1) ───────────────────────────────────────────────

class ProcessingJobCreateRequest(BaseModel):
    """Request body for creating a new processing job."""
    document_id: UUID
    job_type: str = Field(..., description="One of: ocr, text_extraction, cleaning, chunking, embeddings, timeline, summary, analytics")
    priority: str = Field("normal", description="One of: low, normal, high, urgent")
    max_retries: int = Field(3, ge=0, le=10)

    @field_validator("job_type")
    @classmethod
    def validate_job_type(cls, v: str) -> str:
        valid = {"ocr", "text_extraction", "cleaning", "chunking", "embeddings", "timeline", "summary", "analytics"}
        if v not in valid:
            raise ValueError(f"job_type must be one of: {', '.join(sorted(valid))}")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        valid = {"low", "normal", "high", "urgent"}
        if v not in valid:
            raise ValueError(f"priority must be one of: {', '.join(sorted(valid))}")
        return v


class ProcessingJobLogResponse(BaseSchema):
    """A single log entry for a processing job."""
    id: UUID
    job_id: UUID
    event_type: str
    message: str
    metadata_json: Optional[str] = None
    created_at: datetime


class ProcessingJobResponse(BaseSchema):
    """Summary response for a processing job (used in list views)."""
    id: UUID
    user_id: UUID
    document_id: UUID
    case_id: Optional[UUID] = None
    job_type: str
    status: str
    priority: str
    progress_percentage: int
    current_step: Optional[str] = None
    retry_count: int
    max_retries: int
    last_retry_at: Optional[datetime] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @property
    def can_retry(self) -> bool:
        return self.status == "failed" and self.retry_count < self.max_retries

    @property
    def can_cancel(self) -> bool:
        return self.status in {"pending", "queued", "starting", "running"}


class ProcessingJobDetailResponse(ProcessingJobResponse):
    """Full response for a processing job including logs."""
    logs: List[ProcessingJobLogResponse] = []
    error_detail: Optional[str] = None


class ProcessingJobListResponse(BaseModel):
    """Paginated list of processing jobs."""
    items: List[ProcessingJobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ProcessingStatsResponse(BaseModel):
    """Summary statistics for the processing system."""
    pending: int = 0
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    completed_today: int = 0
    average_duration_seconds: Optional[float] = None


from app.schemas.processing_dashboard import (
    ProcessingQueueHealthResponse,
    ProcessingLogItem,
    ProcessingLogsListResponse,
    ProcessingPerformanceResponse,
    JobTimelineEvent,
    JobTimelineResponse,
    JobWarningsResponse,
    JobMetricsResponse,
    ProcessingDashboardStatsResponse,
)


