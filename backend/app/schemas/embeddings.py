from datetime import datetime
from uuid import UUID
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class EmbeddingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    document_id: UUID
    status: str
    progress: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    retry_count: int
    error_message: Optional[str] = None


class EmbeddingJobListResponse(BaseModel):
    items: List[EmbeddingJobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class EmbeddingStatsResponse(BaseModel):
    total_embedded_documents: int
    total_embedded_chunks: int
    average_embedding_time_seconds: Optional[float] = None
    embedding_queue_size: int
    failed_embeddings: int
    retry_count: int
    average_batch_size: int
    processing_throughput_chunks_per_sec: Optional[float] = None


class DocumentEmbeddingStatusResponse(BaseModel):
    document_id: UUID
    status: str  # pending, running, completed, failed, never_embedded
    job_id: Optional[UUID] = None
    progress: int = 0
    error_message: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_version: Optional[str] = None
    embedding_dimension: Optional[int] = None
    total_chunks: int = 0
    embedded_chunks: int = 0
    updated_at: Optional[datetime] = None


class ReembedRequest(BaseModel):
    document_ids: Optional[List[UUID]] = None
