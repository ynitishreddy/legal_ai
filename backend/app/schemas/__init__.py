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
