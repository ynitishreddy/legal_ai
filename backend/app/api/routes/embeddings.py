from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models import User
from app.schemas import (
    EmbeddingJobResponse,
    EmbeddingJobListResponse,
    EmbeddingStatsResponse,
    DocumentEmbeddingStatusResponse,
    ReembedRequest,
    MessageResponse,
)
from app.services.embeddings import DocumentEmbeddingService

router = APIRouter(prefix="/embeddings", tags=["Embeddings"])


# 1. POST /api/embeddings/documents/{id}/embed -> Start embedding job for a document
# Note: The prompt says "POST /documents/{id}/embed", so let's support both paths or mount it accordingly.
# Let's mount both routes under this router, or mount it as:
# @router.post("/documents/{id}/embed") -> prefix is /embeddings, so /embeddings/documents/{id}/embed
# Wait, let's look at the endpoint path in the requirement:
# POST /documents/{id}/embed
# POST /documents/reembed
# GET /embeddings/jobs
# GET /embeddings/jobs/{id}
# GET /embeddings/statistics
# GET /documents/{id}/embedding-status
# POST /embeddings/jobs/{id}/retry
# DELETE /embeddings/jobs/{id}
#
# Ah! To follow the exact paths, let's mount them cleanly! Since the api router has a prefix `/api`,
# if we register this router on `api_router`, let's mount the routes with the exact paths.
# Let's write the router with paths matching exactly, e.g. path "/documents/{document_id}/embed", etc.
# Wait! Let's write the router prefix as empty or `/` so we can mount the routes exactly as requested!
# Yes, if we use router = APIRouter(tags=["Embeddings"]) and define paths like "/documents/{id}/embed",
# "/documents/reembed", "/embeddings/jobs", "/embeddings/jobs/{id}", etc. then they will be registered 
# under /api directly! That matches the required endpoints exactly.

router = APIRouter(tags=["Embeddings"])


@router.post(
    "/documents/{document_id}/embed",
    response_model=EmbeddingJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate embeddings for a document",
    description="Enqueue a background embedding job for a specific document.",
)
async def embed_document(
    document_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> EmbeddingJobResponse:
    service = DocumentEmbeddingService(db)
    job = await service.create_embedding_job(
        user_id=current_user.id,
        document_id=document_id,
    )
    return EmbeddingJobResponse.model_validate(job)


@router.post(
    "/documents/reembed",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Regenerate embeddings",
    description="Regenerate embeddings for one or more documents, or all if none specified.",
)
async def reembed_documents(
    body: ReembedRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    service = DocumentEmbeddingService(db)
    
    document_ids = body.document_ids
    if not document_ids:
        # If no IDs are specified, find all processed documents belonging to user
        from app.models import Document, DocumentStatus
        docs = (
            db.query(Document)
            .filter(Document.owner_id == current_user.id, Document.status == DocumentStatus.PROCESSED)
            .all()
        )
        document_ids = [d.id for d in docs]
    
    if not document_ids:
        return MessageResponse(message="No processed documents found to re-embed.", success=True)

    enqueued_count = 0
    errors = []
    
    for doc_id in document_ids:
        try:
            await service.create_embedding_job(
                user_id=current_user.id,
                document_id=doc_id,
            )
            enqueued_count += 1
        except Exception as e:
            errors.append(f"Document {doc_id}: {str(e)}")

    if errors:
        raise HTTPException(
            status_code=status.HTTP_207_MULTI_STATUS,
            detail=f"Enqueued {enqueued_count} jobs. Errors: {'; '.join(errors)}"
        )
        
    return MessageResponse(
        message=f"Successfully enqueued embedding jobs for {enqueued_count} documents.",
        success=True
    )


@router.get(
    "/embeddings/jobs",
    response_model=EmbeddingJobListResponse,
    summary="List embedding jobs",
    description="Retrieve a paginated list of embedding jobs.",
)
def list_embedding_jobs(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    document_id: Optional[UUID] = Query(None, description="Filter by document ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> EmbeddingJobListResponse:
    service = DocumentEmbeddingService(db)
    jobs, total = service.list_embedding_jobs(
        user_id=current_user.id,
        status_filter=status_filter,
        document_id=document_id,
        page=page,
        page_size=page_size,
    )
    
    import math
    return EmbeddingJobListResponse(
        items=[EmbeddingJobResponse.model_validate(j) for j in jobs],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 0,
    )


@router.get(
    "/embeddings/jobs/{job_id}",
    response_model=EmbeddingJobResponse,
    summary="Get embedding job details",
)
def get_embedding_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> EmbeddingJobResponse:
    service = DocumentEmbeddingService(db)
    job = service.get_embedding_job(job_id=job_id, user_id=current_user.id)
    return EmbeddingJobResponse.model_validate(job)


@router.get(
    "/embeddings/statistics",
    response_model=EmbeddingStatsResponse,
    summary="Get embedding dashboard statistics",
)
def get_embedding_statistics(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> EmbeddingStatsResponse:
    service = DocumentEmbeddingService(db)
    stats = service.get_statistics(user_id=current_user.id)
    return EmbeddingStatsResponse(**stats)


@router.get(
    "/documents/{document_id}/embedding-status",
    response_model=DocumentEmbeddingStatusResponse,
    summary="Get document embedding status",
)
def get_document_embedding_status(
    document_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> DocumentEmbeddingStatusResponse:
    service = DocumentEmbeddingService(db)
    status_data = service.get_embedding_status(document_id=document_id, user_id=current_user.id)
    return DocumentEmbeddingStatusResponse(**status_data)


@router.post(
    "/embeddings/jobs/{job_id}/retry",
    response_model=EmbeddingJobResponse,
    summary="Retry a failed embedding job",
)
async def retry_embedding_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> EmbeddingJobResponse:
    service = DocumentEmbeddingService(db)
    job = await service.retry_embedding_job(job_id=job_id, user_id=current_user.id)
    return EmbeddingJobResponse.model_validate(job)


@router.delete(
    "/embeddings/jobs/{job_id}",
    response_model=MessageResponse,
    summary="Cancel and/or delete embedding job",
)
async def delete_embedding_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    service = DocumentEmbeddingService(db)
    await service.cancel_or_delete_embedding_job(job_id=job_id, user_id=current_user.id)
    return MessageResponse(
        message="Successfully cancelled and/or deleted embedding job.",
        success=True
    )
