from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models import User, VectorSyncJob, Document
from app.schemas import (
    VectorSyncJobResponse,
    VectorSyncJobListResponse,
    VectorStatsResponse,
    VectorHealthResponse,
    QdrantCollectionInfo,
    DocumentSyncStatusResponse,
    MessageResponse,
)
from app.services.vector_sync import VectorSyncService
from app.services.qdrant import QdrantService

router = APIRouter(prefix="/vectors", tags=["Vectors"])


# 1. POST /vectors/sync/document/{id} -> Sync one document's vectors to Qdrant
@router.post(
    "/sync/document/{document_id}",
    response_model=VectorSyncJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def sync_document_vectors(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = VectorSyncService(db)
    try:
        job = await service.create_sync_job(
            user_id=current_user.id,
            document_id=document_id,
        )
        return job
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create sync job: {str(e)}"
        )


# 2. POST /vectors/sync/all -> Trigger sync for all unsynced documents
@router.post(
    "/sync/all",
    response_model=MessageResponse,
)
async def sync_all_unsynced(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = VectorSyncService(db)
    try:
        job_count = await service.sync_all_pending(user_id=current_user.id)
        return MessageResponse(
            message=f"Triggered {job_count} vector database synchronization jobs.",
            success=True,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger sync: {str(e)}"
        )


# 3. POST /vectors/resync -> Force fully reset and resync all vector collections
@router.post(
    "/resync",
    response_model=MessageResponse,
)
async def resync_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = VectorSyncService(db)
    try:
        job_count = await service.force_resync_all(user_id=current_user.id)
        return MessageResponse(
            message=f"Triggered force full vector resynchronization. Spawned {job_count} jobs.",
            success=True,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger full resync: {str(e)}"
        )


# 4. GET /vectors/status -> List vector sync jobs
@router.get(
    "/status",
    response_model=VectorSyncJobListResponse,
)
def get_sync_jobs_status(
    status_filter: Optional[str] = Query(None, alias="status"),
    document_id: Optional[UUID] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = db.query(VectorSyncJob)
    if status_filter:
        query = query.filter(VectorSyncJob.status == status_filter)
    if document_id:
        query = query.filter(VectorSyncJob.document_id == document_id)

    total = query.count()
    items = (
        query.order_by(desc(VectorSyncJob.started_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    total_pages = max(1, (total + page_size - 1) // page_size)

    return VectorSyncJobListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# 5. GET /vectors/statistics -> Aggregate sync stats
@router.get(
    "/statistics",
    response_model=VectorStatsResponse,
)
def get_vector_statistics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = VectorSyncService(db)
    return service.get_statistics()


# 6. GET /vectors/collections -> Get detailed collections information
@router.get(
    "/collections",
    response_model=List[QdrantCollectionInfo],
)
def get_qdrant_collections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    qdrant_svc = QdrantService()
    col = qdrant_svc.get_collection_info()
    
    # Standardize list of collection metadata
    return [
        QdrantCollectionInfo(
            name=col["name"],
            status=col["status"],
            vectors_count=col["vectors_count"],
            dimension=col["dimension"],
            indexed_vectors_count=col["indexed_vectors_count"],
            segments_count=col["segments_count"],
        )
    ]


# 7. GET /vectors/health -> Check connection to Qdrant cluster
@router.get(
    "/health",
    response_model=VectorHealthResponse,
)
def get_qdrant_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    qdrant_svc = QdrantService()
    health = qdrant_svc.health_check()
    return VectorHealthResponse(
        status=health["status"],
        mode=health["mode"],
        collections_count=health["collections_count"],
        target_collection=health["target_collection"],
        vector_count=health["vector_count"],
        status_detail=health["status_detail"],
    )


# 8. GET /vectors/document/{id}/sync-status -> Get single document sync details
@router.get(
    "/document/{document_id}/sync-status",
    response_model=DocumentSyncStatusResponse,
)
def get_document_sync_status(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = VectorSyncService(db)
    return service.get_sync_status(document_id)


# 9. DELETE /vectors/document/{id} -> Delete document vectors from Qdrant
@router.delete(
    "/document/{document_id}",
    response_model=MessageResponse,
)
def delete_document_vectors(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = VectorSyncService(db)
    success = service.delete_document_vectors(document_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete vectors from vector storage."
        )
    return MessageResponse(
        message="Vector database records deleted successfully.",
        success=True,
    )


# 10. POST /vectors/jobs/{id}/retry -> Retry a failed sync job
@router.post(
    "/jobs/{job_id}/retry",
    response_model=VectorSyncJobResponse,
)
async def retry_sync_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = VectorSyncService(db)
    return await service.retry_sync_job(job_id)
