import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, ForeignKey, Integer, Float, Boolean, DateTime, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models import utcnow, JobStatus


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    summary_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    case: Mapped["Case"] = relationship("Case")
    versions: Mapped[list["SummaryVersion"]] = relationship(
        "SummaryVersion", back_populates="summary", cascade="all, delete-orphan", order_by="desc(SummaryVersion.version)"
    )


class SummaryVersion(Base):
    __tablename__ = "summary_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("summaries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0)
    citation_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    completeness_score: Mapped[float] = mapped_column(Float, default=1.0)
    token_usage_json: Mapped[str | None] = mapped_column(Text, nullable=True) # JSON string
    validation_status: Mapped[str] = mapped_column(String(50), default="passed") # passed, failed
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    summary: Mapped["Summary"] = relationship("Summary", back_populates="versions")
    citations: Mapped[list["SummaryCitation"]] = relationship(
        "SummaryCitation", back_populates="summary_version", cascade="all, delete-orphan"
    )


class SummaryCitation(Base):
    __tablename__ = "summary_citations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    summary_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("summary_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    citation_type: Mapped[str] = mapped_column(String(50), nullable=False) # fact, timeline_event, entity, document, chunk
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_title: Mapped[str] = mapped_column(String(255), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    summary_version: Mapped["SummaryVersion"] = relationship("SummaryVersion", back_populates="citations")


class SummaryCache(Base):
    __tablename__ = "summary_caches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    summary_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    summary_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("summary_versions.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    summary_version: Mapped["SummaryVersion"] = relationship("SummaryVersion")


class SummaryGenerationJob(Base):
    __tablename__ = "summary_generation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    summary_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, values_callable=lambda e: [m.value for m in e], name="jobstatus", create_type=False),
        default=JobStatus.PENDING,
        nullable=False,
        index=True
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    case: Mapped["Case"] = relationship("Case")
