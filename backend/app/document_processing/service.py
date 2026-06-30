"""
app.document_processing.service — DocumentProcessingService database CRUD layer.
"""

import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Document
from app.document_processing.models import DocumentText
from app.document_processing.extractors.base import ExtractionResult

logger = logging.getLogger(__name__)


class DocumentProcessingService:
    """
    CRUD database operations for document text extraction results.
    Integrates with Core Document models and checks user ownership.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def _verify_document_owner(self, document_id: UUID, user_id: UUID) -> Document:
        """Verify the document exists and belongs to the user."""
        doc: Optional[Document] = self.db.get(Document, document_id)
        if doc is None or doc.owner_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found or access denied.",
            )
        return doc

    def get_document_text(self, document_id: UUID, user_id: UUID) -> DocumentText:
        """
        Retrieve the extracted text record for a document.
        Raises 404 if the document does not exist, belongs to another user,
        or has not been processed yet.
        """
        # Ensure document belongs to user
        self._verify_document_owner(document_id, user_id)

        doc_text = (
            self.db.query(DocumentText)
            .filter(DocumentText.document_id == document_id)
            .first()
        )
        if not doc_text:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document text has not been extracted yet. Start a processing task.",
            )
        return doc_text

    def save_extraction_result(
        self,
        document_id: UUID,
        result: ExtractionResult,
    ) -> DocumentText:
        """
        Persist an ExtractionResult to the database.
        Upserts the record: updates it if it exists, creates a new one if not.
        """
        # Check if record already exists
        doc_text = (
            self.db.query(DocumentText)
            .filter(DocumentText.document_id == document_id)
            .first()
        )

        metadata_str = json.dumps(result.metadata) if result.metadata else None
        warnings_str = json.dumps(result.warnings) if result.warnings else None

        if doc_text:
            logger.info("DocumentProcessingService: Updating existing extracted text for document %s", document_id)
            doc_text.extraction_method = result.extraction_method
            doc_text.extracted_text = result.extracted_text
            doc_text.page_count = result.page_count
            doc_text.confidence_score = result.confidence_score
            doc_text.has_ocr = result.has_ocr
            doc_text.processing_time = result.processing_time
            doc_text.language = result.language_detected
            doc_text.metadata_json = metadata_str
            doc_text.warnings_json = warnings_str
        else:
            logger.info("DocumentProcessingService: Saving new extracted text for document %s", document_id)
            doc_text = DocumentText(
                document_id=document_id,
                extraction_method=result.extraction_method,
                extracted_text=result.extracted_text,
                page_count=result.page_count,
                confidence_score=result.confidence_score,
                has_ocr=result.has_ocr,
                processing_time=result.processing_time,
                language=result.language_detected,
                metadata_json=metadata_str,
                warnings_json=warnings_str,
            )
            self.db.add(doc_text)

        # Update core document status to processed
        doc: Optional[Document] = self.db.get(Document, document_id)
        if doc:
            from app.models import DocumentStatus
            doc.status = DocumentStatus.PROCESSED
            doc.page_count = result.page_count

        self.db.commit()
        self.db.refresh(doc_text)
        return doc_text

    def save_cleaning_result(
        self,
        document_id: UUID,
        cleaned_text: str,
        report: dict,
        processing_time: float,
    ) -> DocumentText:
        """
        Persists the cleaned, normalized text and the cleaning execution report.
        """
        doc_text = (
            self.db.query(DocumentText)
            .filter(DocumentText.document_id == document_id)
            .first()
        )
        if not doc_text:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Extracted document text record not found. Cannot clean text before extraction.",
            )

        doc_text.cleaned_text = cleaned_text
        doc_text.cleaning_version = report.get("version", "1.0.0")
        doc_text.cleaning_report_json = json.dumps(report)
        doc_text.cleaning_processing_time = processing_time

        self.db.commit()
        self.db.refresh(doc_text)
        return doc_text



# ── FastAPI Dependency injection factory ──────────────────────────────────────

def get_document_processing_service(db: Session) -> DocumentProcessingService:
    return DocumentProcessingService(db)
