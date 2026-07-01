from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

class BaseSchema(BaseModel):
    model_config = {
        "from_attributes": True
    }


class VectorSyncJobResponse(BaseSchema):
    id: UUID
    document_id: UUID
    status: str
    progress: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    retry_count: int
    error_message: Optional[str] = None


class VectorSyncJobListResponse(BaseModel):
    items: List[VectorSyncJobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class VectorStatsResponse(BaseModel):
    total_vectors: int
    synced_vectors: int
    pending_vectors: int
    failed_vectors: int
    embedding_queue_size: int
    sync_queue_size: int
    collection_name: str
    collection_status: str
    collection_dimension: int
    qdrant_vectors_count: int


class VectorHealthResponse(BaseModel):
    status: str
    mode: str
    collections_count: int
    target_collection: str
    vector_count: int
    status_detail: str


class QdrantCollectionInfo(BaseModel):
    name: str
    status: str
    vectors_count: int
    dimension: int
    indexed_vectors_count: int
    segments_count: int


class DocumentSyncStatusResponse(BaseModel):
    document_id: str
    status: str
    job_id: Optional[str] = None
    progress: int
    error_message: Optional[str] = None
    total_chunks: int
    embeddings_count: int
    synced_count: int
    updated_at: Optional[str] = None


class VectorSyncRequest(BaseModel):
    document_ids: Optional[List[UUID]] = None
