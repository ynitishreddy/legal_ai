"""
app.document_processing.chunking.schemas — Pydantic models for chunking config, results, and responses.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class ChunkingConfig(BaseModel):
    """Configuration limits and rules for document chunking."""
    max_characters: int = Field(default=3000, description="Hard upper limit on character count per chunk.")
    max_words: int = Field(default=500, description="Hard upper limit on word count per chunk.")
    estimated_tokens: int = Field(default=800, description="Approximate token count threshold.")
    overlap_size: int = Field(default=50, description="Configurable overlap in words between contiguous chunks.")
    min_chunk_size: int = Field(default=50, description="Minimum characters required to form a valid chunk.")


class ChunkResult(BaseModel):
    """Represents a successfully generated text chunk prior to DB persistence."""
    text: str
    page_start: int
    page_end: int
    paragraph_start: int
    paragraph_end: int
    section_title: Optional[str] = None
    word_count: int
    character_count: int
    estimated_tokens: int


class DocumentChunkResponse(BaseModel):
    """API response model representing a single document chunk."""
    id: UUID
    document_id: UUID
    chunk_index: int
    section_name: Optional[str] = None
    chunk_text: str
    page_start: int
    page_end: int
    paragraph_start: int
    paragraph_end: int
    word_count: int
    character_count: int
    estimated_tokens: int
    overlap_previous: bool
    overlap_next: bool
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    class Config:
        from_attributes = True


class ChunkStatsResponse(BaseModel):
    """API response model containing metrics and execution statistics of document chunking."""
    total_chunks: int
    average_chunk_size: float
    largest_chunk: int
    smallest_chunk: int
    average_words: float
    estimated_tokens: int
    strategy_used: str


class ChunkBoundary(BaseModel):
    """Marks the coordinates of a chunk boundary for visualization."""
    chunk_index: int
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    preview_snippet: str


class ChunkPreviewResponse(BaseModel):
    """API response containing list of visual boundary indices for previewing splits."""
    document_id: UUID
    boundaries: List[ChunkBoundary]
