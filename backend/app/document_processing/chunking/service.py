"""
app.document_processing.chunking.service — Service methods for document chunks database persistence.
"""

import json
import uuid
from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.document_processing.models import DocumentChunk, DocumentText
from app.document_processing.chunking.schemas import (
    ChunkResult,
    DocumentChunkResponse,
    ChunkStatsResponse,
    ChunkPreviewResponse,
    ChunkBoundary,
)


class DocumentChunkingService:
    """
    Manages persistence operations for document text chunks.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def delete_document_chunks(self, document_id: UUID) -> None:
        """
        Deletes all existing chunks for a document.
        """
        self.db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
        self.db.commit()

    def persist_chunks(
        self,
        document_id: UUID,
        chunks: List[ChunkResult],
        strategy_name: str,
        report: Dict[str, Any]
    ) -> List[DocumentChunk]:
        """
        Cleans existing chunks and persists a fresh list of trace-ready chunks.
        """
        # First, delete stale chunks to prevent duplicates
        self.delete_document_chunks(document_id)

        persisted_chunks = []
        total_chunks = len(chunks)
        is_sliding = "SlidingWindow" in strategy_name

        for idx, c in enumerate(chunks):
            # Create traceability metadata
            meta = {
                "chunk_id": str(uuid.uuid4()),
                "document_id": str(document_id),
                "strategy_used": strategy_name,
                "chunking_version": report.get("chunking_version", "1.0.0"),
                "total_chunks": total_chunks,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            db_chunk = DocumentChunk(
                document_id=document_id,
                chunk_index=idx,
                section_name=c.section_title or "General",
                chunk_text=c.text,
                page_start=c.page_start,
                page_end=c.page_end,
                paragraph_start=c.paragraph_start,
                paragraph_end=c.paragraph_end,
                word_count=c.word_count,
                character_count=c.character_count,
                estimated_tokens=c.estimated_tokens,
                overlap_previous=is_sliding and idx > 0,
                overlap_next=is_sliding and idx < total_chunks - 1,
                metadata_json=json.dumps(meta),
            )
            self.db.add(db_chunk)
            persisted_chunks.append(db_chunk)

        self.db.commit()
        
        # Refresh persisted instances
        for pc in persisted_chunks:
            self.db.refresh(pc)

        return persisted_chunks

    def get_document_chunks(self, document_id: UUID) -> List[DocumentChunk]:
        """
        Retrieves all chunks for a document ordered by index.
        """
        return (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )

    def get_chunk_by_id(self, chunk_id: UUID) -> DocumentChunk:
        """
        Retrieves a single chunk by its primary key ID.
        """
        chunk = self.db.get(DocumentChunk, chunk_id)
        if not chunk:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document chunk with ID {chunk_id} not found."
            )
        return chunk

    def get_document_chunk_stats(self, document_id: UUID) -> ChunkStatsResponse:
        """
        Compiles summary metrics across all chunks of a document.
        """
        chunks = self.get_document_chunks(document_id)
        if not chunks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No chunks found for this document. It might not be processed yet."
            )

        total_chunks = len(chunks)
        char_lens = [c.character_count for c in chunks]
        word_counts = [c.word_count for c in chunks]
        token_estimates = [c.estimated_tokens for c in chunks]

        # Determine strategy from metadata if available
        strategy = "ParagraphChunkingStrategy"
        if chunks[0].metadata_json:
            try:
                meta = json.loads(chunks[0].metadata_json)
                strategy = meta.get("strategy_used", strategy)
            except Exception:
                pass

        return ChunkStatsResponse(
            total_chunks=total_chunks,
            average_chunk_size=sum(char_lens) / total_chunks,
            largest_chunk=max(char_lens),
            smallest_chunk=min(char_lens),
            average_words=sum(word_counts) / total_chunks,
            estimated_tokens=sum(token_estimates),
            strategy_used=strategy,
        )

    def get_document_chunk_preview(self, document_id: UUID) -> ChunkPreviewResponse:
        """
        Generates character split indices and text snippets for boundary visualization.
        """
        chunks = self.get_document_chunks(document_id)
        
        boundaries = []
        char_cursor = 0

        for c in chunks:
            char_len = len(c.chunk_text)
            char_end = char_cursor + char_len
            
            boundaries.append(
                ChunkBoundary(
                    chunk_index=c.chunk_index,
                    page_start=c.page_start,
                    page_end=c.page_end,
                    char_start=char_cursor,
                    char_end=char_end,
                    preview_snippet=c.chunk_text[:120].strip() + ("..." if char_len > 120 else "")
                )
            )
            # Add one space character representation as default separator gap
            char_cursor = char_end + 1

        return ChunkPreviewResponse(
            document_id=document_id,
            boundaries=boundaries,
        )


def get_document_chunking_service(db: Session) -> DocumentChunkingService:
    return DocumentChunkingService(db)
