"""
app.api.routes.document_chunking — REST API endpoints for document text chunking.
"""

import json
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models import User
from app.document_processing.service import get_document_processing_service
from app.document_processing.chunking.service import get_document_chunking_service
from app.document_processing.chunking.schemas import (
    DocumentChunkResponse,
    ChunkStatsResponse,
    ChunkPreviewResponse,
)

router = APIRouter(prefix="/documents", tags=["Document Chunking"])


@router.get("/{id}/chunks", response_model=List[DocumentChunkResponse])
def get_document_chunks(
    id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    List all persisted chunks for a specific document.
    Only the document owner may access this endpoint.
    """
    # 1. Verify ownership
    proc_service = get_document_processing_service(db)
    proc_service._verify_document_owner(id, current_user.id)

    # 2. Retrieve chunks
    chunk_service = get_document_chunking_service(db)
    chunks = chunk_service.get_document_chunks(id)
    
    response = []
    for c in chunks:
        meta = {}
        if c.metadata_json:
            try:
                meta = json.loads(c.metadata_json)
            except Exception:
                pass
                
        response.append(
            DocumentChunkResponse(
                id=c.id,
                document_id=c.document_id,
                chunk_index=c.chunk_index,
                section_name=c.section_name,
                chunk_text=c.chunk_text,
                page_start=c.page_start,
                page_end=c.page_end,
                paragraph_start=c.paragraph_start,
                paragraph_end=c.paragraph_end,
                word_count=c.word_count,
                character_count=c.character_count,
                estimated_tokens=c.estimated_tokens,
                overlap_previous=c.overlap_previous,
                overlap_next=c.overlap_next,
                metadata=meta,
                created_at=c.created_at,
            )
        )
    return response


@router.get("/{id}/chunks/{chunk_id}", response_model=DocumentChunkResponse)
def get_chunk_details(
    id: UUID,
    chunk_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve details for a single, specific text chunk.
    Only the document owner may access this endpoint.
    """
    # 1. Verify ownership
    proc_service = get_document_processing_service(db)
    proc_service._verify_document_owner(id, current_user.id)

    # 2. Retrieve chunk
    chunk_service = get_document_chunking_service(db)
    c = chunk_service.get_chunk_by_id(chunk_id)

    if c.document_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chunk does not belong to the specified document."
        )

    meta = {}
    if c.metadata_json:
        try:
            meta = json.loads(c.metadata_json)
        except Exception:
            pass

    return DocumentChunkResponse(
        id=c.id,
        document_id=c.document_id,
        chunk_index=c.chunk_index,
        section_name=c.section_name,
        chunk_text=c.chunk_text,
        page_start=c.page_start,
        page_end=c.page_end,
        paragraph_start=c.paragraph_start,
        paragraph_end=c.paragraph_end,
        word_count=c.word_count,
        character_count=c.character_count,
        estimated_tokens=c.estimated_tokens,
        overlap_previous=c.overlap_previous,
        overlap_next=c.overlap_next,
        metadata=meta,
        created_at=c.created_at,
    )


@router.get("/{id}/chunk-stats", response_model=ChunkStatsResponse)
def get_document_chunk_stats(
    id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve statistical breakdown metrics of generated chunks.
    Only the document owner may access this endpoint.
    """
    # 1. Verify ownership
    proc_service = get_document_processing_service(db)
    proc_service._verify_document_owner(id, current_user.id)

    # 2. Compile stats
    chunk_service = get_document_chunking_service(db)
    return chunk_service.get_document_chunk_stats(id)


@router.get("/{id}/chunk-preview", response_model=ChunkPreviewResponse)
def get_document_chunk_preview(
    id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve list of character indices and text boundary previews for visualization.
    Only the document owner may access this endpoint.
    """
    # 1. Verify ownership
    proc_service = get_document_processing_service(db)
    proc_service._verify_document_owner(id, current_user.id)

    # 2. Compile boundary preview
    chunk_service = get_document_chunking_service(db)
    return chunk_service.get_document_chunk_preview(id)
