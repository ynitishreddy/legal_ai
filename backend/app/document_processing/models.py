"""
app.document_processing.models — DocumentText database model.
"""

import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models import utcnow


class DocumentText(Base):
    """
    Stores extracted text and metadata for case documents.
    Kept separate from the core documents table to facilitate versioning and performance.
    """
    __tablename__ = "document_texts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Extraction details
    extraction_method: Mapped[str] = mapped_column(String(50), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    has_ocr: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    processing_time: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # JSON metadata for extensible storage
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string of metadata
    warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string of warnings

    # Cleaning details (Phase 5.3)
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleaning_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cleaning_report_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string of cleaning report
    cleaning_processing_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="extracted_text")


class DocumentChunk(Base):
    """
    Stores individual text chunks generated from case documents
    for vector search, hybrid retrieval, and downstream RAG chat.
    """
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    section_name: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    paragraph_start: Mapped[int] = mapped_column(Integer, nullable=False)
    paragraph_end: Mapped[int] = mapped_column(Integer, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    overlap_previous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    overlap_next: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Traceability & audit metadata
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

