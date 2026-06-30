"""
app.document_processing.schemas — Pydantic models for text extraction results and API responses.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class DocumentTextResponse(BaseModel):
    """API response model containing complete extracted text."""
    document_id: UUID
    extraction_method: str
    extracted_text: str
    page_count: int
    confidence_score: float
    has_ocr: bool
    processing_time: float
    language: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentMetadataResponse(BaseModel):
    """API response model containing document metadata and warnings."""
    document_id: UUID
    metadata: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)

    @field_validator("metadata", mode="before")
    @classmethod
    def parse_metadata_json(cls, v: Any) -> Dict[str, Any]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}

    @field_validator("warnings", mode="before")
    @classmethod
    def parse_warnings_json(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return []
        return v or []


class DocumentTextPreviewResponse(BaseModel):
    """API response model containing a truncated preview of extracted text."""
    document_id: UUID
    preview_text: str
    page_count: int
    confidence_score: float
    has_ocr: bool
    extraction_method: str
    created_at: datetime


class DocumentCleanedTextResponse(BaseModel):
    """API response model containing cleaned text."""
    document_id: UUID
    cleaned_text: Optional[str] = None
    cleaning_version: Optional[str] = None
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentCleaningReportResponse(BaseModel):
    """API response model containing text cleaning report and metrics."""
    document_id: UUID
    cleaning_version: Optional[str] = None
    cleaning_report: Dict[str, Any] = Field(default_factory=dict)
    cleaning_processing_time: Optional[float] = None
    updated_at: datetime

    @field_validator("cleaning_report", mode="before")
    @classmethod
    def parse_report_json(cls, v: Any) -> Dict[str, Any]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}


class DocumentTextComparisonResponse(BaseModel):
    """API response model containing a raw vs cleaned text comparison and diff metrics."""
    document_id: UUID
    raw_text: str
    cleaned_text: Optional[str] = None
    summary: Dict[str, Any] = Field(default_factory=dict)

