from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models import User, RetrievalLog
from app.document_processing.models import DocumentChunk
from app.schemas import (
    RetrievalSearchRequest,
    RetrievalChunkResponse,
    ContextWindowRequest,
    ContextWindowResponse,
    RetrievalLogResponse,
    RetrievalLogListResponse,
    RetrievalStatsResponse,
    RetrievalHealthResponse,
    ChunkPreviewRequest,
    MessageResponse,
)
from app.services.retriever import RetrieverService

router = APIRouter(prefix="/retrieval", tags=["Retrieval"])


# 1. POST /api/retrieval/search -> Semantic retrieval search
@router.post(
    "/search",
    response_model=List[RetrievalChunkResponse],
)
async def semantic_search(
    request: RetrievalSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = RetrieverService(db)
    try:
        filters = {
            "case_id": request.case_id,
            "document_id": request.document_id,
            "document_type": request.document_type,
            "filename": request.filename,
            "tags": request.tags,
            "page_number": request.page_number,
            "section_title": request.section_title,
        }
        results = service.retrieve_semantic(
            user_id=current_user.id,
            query_text=request.query_text,
            filters=filters,
            top_k=request.top_k,
            score_threshold=request.score_threshold,
        )
        return results
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Semantic retrieval failed: {str(e)}"
        )


# 2. POST /api/retrieval/context -> Build merged context window
@router.post(
    "/context",
    response_model=ContextWindowResponse,
)
async def build_context_window(
    request: ContextWindowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = RetrieverService(db)
    try:
        context_text = service.build_context_window(
            chunks=request.chunks,
            max_tokens=request.max_tokens,
        )
        return ContextWindowResponse(
            context_text=context_text,
            total_chunks_merged=len(request.chunks),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to build context window: {str(e)}"
        )


# 3. POST /api/retrieval/preview -> Retrieve single chunk preview
@router.post(
    "/preview",
    response_model=RetrievalChunkResponse,
)
async def preview_chunk(
    request: ChunkPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # Fetch from DB and build citation response
    chunk = db.get(DocumentChunk, request.chunk_id)
    if not chunk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document chunk {request.chunk_id} not found."
        )
    
    doc = chunk.document
    if doc.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this document chunk."
        )

    # Get first embedding version or fallback
    emb_version = doc.embeddings[0].embedding_version if (hasattr(doc, "embeddings") and doc.embeddings) else "1.5"

    return RetrievalChunkResponse(
        chunk_id=chunk.id,
        document_id=doc.id,
        document_name=doc.title or doc.filename,
        case_id=str(doc.case_id) if doc.case_id else "",
        page_number=chunk.page_start,
        section_title=chunk.section_name or "",
        similarity_score=1.0,
        embedding_version=emb_version,
        source_path=doc.file_path or doc.storage_path or f"uploads/{doc.filename}",
        text=chunk.chunk_text,
        chunk_index=chunk.chunk_index,
    )


# 4. GET /api/retrieval/history -> Fetch search logging history
@router.get(
    "/history",
    response_model=RetrievalLogListResponse,
)
async def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = (
        db.query(RetrievalLog)
        .filter(RetrievalLog.user_id == current_user.id)
        .order_by(desc(RetrievalLog.created_at))
    )
    
    total = query.count()
    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()
    
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    return RetrievalLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# 5. GET /api/retrieval/statistics -> Dashboard stats API
@router.get(
    "/statistics",
    response_model=RetrievalStatsResponse,
)
async def get_statistics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = RetrieverService(db)
    try:
        stats_data = service.get_statistics()
        return RetrievalStatsResponse(**stats_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load retrieval stats: {str(e)}"
        )


# 6. GET /api/retrieval/health -> Invalidate caches / connection monitoring
@router.get(
    "/health",
    response_model=RetrievalHealthResponse,
)
async def get_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.services.retriever import RetrieverService
    
    # Calculate caching stats
    emb_size = len(RetrieverService._embedding_cache)
    ret_size = len(RetrieverService._retrieval_cache)

    return RetrievalHealthResponse(
        status="healthy",
        active_queries_count=RetrieverService._stats["total_requests"],
        embedding_cache_size=emb_size,
        retrieval_cache_size=ret_size,
    )


# 7. DELETE /api/retrieval/history/{id} -> Delete single audit log
@router.delete(
    "/history/{log_id}",
    response_model=MessageResponse,
)
async def delete_history(
    log_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = RetrieverService(db)
    try:
        service.delete_history_entry(log_id, current_user.id)
        return MessageResponse(message="Query log entry deleted successfully.", success=True)
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete history log: {str(e)}"
        )
