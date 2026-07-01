import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    LAWYER = "lawyer"


class CaseStatus(str, enum.Enum):
    OPEN = "open"
    ACTIVE = "active"
    PENDING = "pending"
    ON_HOLD = "on_hold"
    CLOSED = "closed"
    ARCHIVED = "archived"


class CasePriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class DocumentType(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    OTHER = "other"


class UploadStatus(str, enum.Enum):
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    NOT_STARTED = "not_started"


class DocumentCategory(str, enum.Enum):
    PDF = "pdf"
    WORD = "word"
    TEXT = "text"
    IMAGE = "image"
    OTHER = "other"


class ChatRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# Phase 5.1 — Background Processing Enums
# ---------------------------------------------------------------------------

class JobStatus(str, enum.Enum):
    """State machine for processing jobs."""
    PENDING = "pending"
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, enum.Enum):
    """Supported processing job types. Only identifiers — no implementation yet."""
    OCR = "ocr"
    TEXT_EXTRACTION = "text_extraction"
    CLEANING = "cleaning"
    CHUNKING = "chunking"
    EMBEDDINGS = "embeddings"
    VECTOR_SYNC = "vector_sync"
    TIMELINE = "timeline"
    CASE_INTELLIGENCE = "case_intelligence"
    SUMMARY = "summary"
    ANALYTICS = "analytics"


class JobPriority(str, enum.Enum):
    """Job scheduling priority."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class JobLogEventType(str, enum.Enum):
    """Event categories for processing job logs."""
    CREATED = "created"
    QUEUED = "queued"
    STARTED = "started"
    PROGRESS = "progress"
    RETRY = "retry"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    INFO = "info"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, values_callable=lambda e: [m.value for m in e]), default=UserRole.USER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    cases: Mapped[list["Case"]] = relationship("Case", back_populates="owner", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="owner", cascade="all, delete-orphan"
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession", back_populates="user", cascade="all, delete-orphan"
    )
    analytics_records: Mapped[list["AnalyticsRecord"]] = relationship(
        "AnalyticsRecord", back_populates="user", cascade="all, delete-orphan"
    )
    processing_jobs: Mapped[list["ProcessingJob"]] = relationship(
        "ProcessingJob", back_populates="user", cascade="all, delete-orphan"
    )


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_number: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    court_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(255), nullable=True)
    judge_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opposing_party: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, values_callable=lambda e: [m.value for m in e]),
        default=CaseStatus.OPEN,
        nullable=False,
    )
    priority: Mapped[CasePriority] = mapped_column(
        Enum(CasePriority, values_callable=lambda e: [m.value for m in e]),
        default=CasePriority.MEDIUM,
        nullable=False,
    )
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    owner: Mapped["User"] = relationship("User", back_populates="cases")
    documents: Mapped[list["Document"]] = relationship("Document", back_populates="case")
    timeline_events: Mapped[list["TimelineEvent"]] = relationship(
        "TimelineEvent", back_populates="case", cascade="all, delete-orphan"
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship("ChatSession", back_populates="case")
    analytics_records: Mapped[list["AnalyticsRecord"]] = relationship(
        "AnalyticsRecord", back_populates="case"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType, values_callable=lambda e: [m.value for m in e]), default=DocumentType.OTHER)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus, values_callable=lambda e: [m.value for m in e]), default=DocumentStatus.UPLOADED)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="SET NULL"), nullable=True
    )
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stored_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_extension: Mapped[str | None] = mapped_column(String(10), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    upload_status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus, values_callable=lambda e: [m.value for m in e]),
        default=UploadStatus.COMPLETED,
        nullable=False,
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, values_callable=lambda e: [m.value for m in e]),
        default=ProcessingStatus.PENDING,
        nullable=False,
    )
    document_category: Mapped[DocumentCategory] = mapped_column(
        Enum(DocumentCategory, values_callable=lambda e: [m.value for m in e]),
        default=DocumentCategory.OTHER,
        nullable=False,
    )
    user_tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated tags
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    owner: Mapped["User"] = relationship("User", back_populates="documents")
    case: Mapped["Case | None"] = relationship("Case", back_populates="documents")
    timeline_events: Mapped[list["TimelineEvent"]] = relationship(
        "TimelineEvent", back_populates="document"
    )
    processing_jobs: Mapped[list["ProcessingJob"]] = relationship(
        "ProcessingJob", back_populates="document", cascade="all, delete-orphan"
    )
    extracted_text: Mapped["DocumentText | None"] = relationship(
        "DocumentText", back_populates="document", uselist=False, cascade="all, delete-orphan"
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    
    # Conversational RAG / Timeline metadata updates (Phase 8.1)
    event_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    original_date: Mapped[str | None] = mapped_column(String(100), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    case: Mapped["Case"] = relationship("Case", back_populates="timeline_events")
    document: Mapped["Document | None"] = relationship("Document", back_populates="timeline_events")


class EventRelationship(Base):
    __tablename__ = "event_relationships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("timeline_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    child_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("timeline_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)

    parent_event: Mapped["TimelineEvent"] = relationship(
        "TimelineEvent", foreign_keys=[parent_event_id]
    )
    child_event: Mapped["TimelineEvent"] = relationship(
        "TimelineEvent", foreign_keys=[child_event_id]
    )



class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), default="New Chat")
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped["User"] = relationship("User", back_populates="chat_sessions")
    case: Mapped["Case | None"] = relationship("Case", back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[ChatRole] = mapped_column(Enum(ChatRole, values_callable=lambda e: [m.value for m in e]), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citations_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    token_usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AnalyticsRecord(Base):
    __tablename__ = "analytics_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    metric_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="SET NULL"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="analytics_records")
    case: Mapped["Case | None"] = relationship("Case", back_populates="analytics_records")


# ---------------------------------------------------------------------------
# Phase 5.1 — Processing Job Models
# ---------------------------------------------------------------------------

class ProcessingJob(Base):
    """
    Represents a background processing task for a document.

    Lifecycle: PENDING → QUEUED → STARTING → RUNNING → COMPLETED | FAILED | CANCELLED
    Supports retries up to max_retries.
    """
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Classification
    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        index=True,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, values_callable=lambda e: [m.value for m in e]),
        default=JobStatus.PENDING,
        nullable=False,
        index=True,
    )
    priority: Mapped[JobPriority] = mapped_column(
        Enum(JobPriority, values_callable=lambda e: [m.value for m in e]),
        default=JobPriority.NORMAL,
        nullable=False,
    )

    # Progress tracking
    progress_percentage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Retry support
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Error information
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # stack trace / detail

    # Timestamps
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="processing_jobs")
    document: Mapped["Document"] = relationship("Document", back_populates="processing_jobs")
    case: Mapped["Case | None"] = relationship("Case")
    logs: Mapped[list["ProcessingJobLog"]] = relationship(
        "ProcessingJobLog",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ProcessingJobLog.created_at",
    )


class ProcessingJobLog(Base):
    """
    Chronological event log for a processing job.

    Each row represents one event in the job lifecycle.
    """
    __tablename__ = "processing_job_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[JobLogEventType] = mapped_column(
        Enum(JobLogEventType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    job: Mapped["ProcessingJob"] = relationship("ProcessingJob", back_populates="logs")


# Phase 5.2 — Extracted document texts
from app.document_processing.models import DocumentText, DocumentChunk

# Phase 6.1 — Embedding Models
from app.models.embeddings import DocumentEmbedding, EmbeddingJob, VectorSyncJob

# Phase 6.3 — Retrieval Models
from app.models.retrieval import RetrievalLog


# Phase 8.2 — Case Intelligence Models
class LegalFact(Base):
    __tablename__ = "legal_facts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    chunk_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    citation_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    
    # Extensions for Phase 8.2 (v1.5.1)
    category: Mapped[str] = mapped_column(String(50), default="Factual Findings", server_default="Factual Findings", nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5", nullable=False)
    processing_version: Mapped[str] = mapped_column(String(20), default="1.0.0", server_default="1.0.0", nullable=False)
    supporting_citations: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string


class LegalEntity(Base):
    __tablename__ = "legal_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True) # party, judge, court, advocate, witness
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[str | None] = mapped_column(String(500), nullable=True) # comma-separated
    role: Mapped[str | None] = mapped_column(String(100), nullable=True) # e.g. plaintiff, counsel, etc.
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Extensions for Phase 8.2 (v1.5.1)
    canonical_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resolution_status: Mapped[str] = mapped_column(String(50), default="unresolved", server_default="unresolved", nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    merge_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    confidence_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string


class LegalIssue(Base):
    __tablename__ = "legal_issues"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    issue_text: Mapped[str] = mapped_column(Text, nullable=False)
    issue_category: Mapped[str] = mapped_column(String(50), nullable=False) # civil, criminal, constitutional, procedural
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Extensions for Phase 8.2 (v1.5.1)
    labels: Mapped[str | None] = mapped_column(Text, nullable=True)  # Comma-separated labels
    confidence_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string


class ClaimDefense(Base):
    __tablename__ = "claims_defenses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True) # claim_primary, claim_alternative, claim_counter, claim_cross, etc.
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Extensions for Phase 8.2 (v1.5.1)
    confidence_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string


class LegalEvidence(Base):
    __tablename__ = "legal_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False) # exhibit, witness_testimony, electronic, forensic
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Extensions for Phase 8.2 (v1.5.1)
    strength_score: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5", nullable=False)
    confidence_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string


class ActStatute(Base):
    __tablename__ = "acts_statutes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    act_name: Mapped[str] = mapped_column(String(255), nullable=False)
    section_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    normalized_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Extensions for Phase 8.2 (v1.5.1)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("acts_statutes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    aliases: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confidence_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string


class EntityRelationship(Base):
    __tablename__ = "entity_relationships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False) # entity, claim, evidence, fact, act
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False) # entity, claim, evidence, fact, act
    relationship_type: Mapped[str] = mapped_column(String(100), nullable=False) # represented_by, issued, supports, disputed_by, referenced_in
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Extensions for Phase 8.2 (v1.5.1)
    reasoning_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    source_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    confidence_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string



