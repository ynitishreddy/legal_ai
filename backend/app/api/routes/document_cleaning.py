"""
app.api.routes.document_cleaning — REST API endpoints for document text cleaning & reports.
"""

import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models import User
from app.document_processing.service import get_document_processing_service
from app.document_processing.schemas import (
    DocumentCleanedTextResponse,
    DocumentCleaningReportResponse,
    DocumentTextComparisonResponse,
)

router = APIRouter(prefix="/documents", tags=["Document Cleaning"])


@router.get("/{id}/cleaned-text", response_model=DocumentCleanedTextResponse)
def get_cleaned_text(
    id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve the cleaned, normalized text for a document.
    Only the document owner may access this endpoint.
    """
    service = get_document_processing_service(db)
    doc_text = service.get_document_text(id, current_user.id)

    if not doc_text.cleaned_text:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document text has not been cleaned yet.",
        )

    return DocumentCleanedTextResponse(
        document_id=doc_text.document_id,
        cleaned_text=doc_text.cleaned_text,
        cleaning_version=doc_text.cleaning_version,
        updated_at=doc_text.updated_at,
    )


@router.get("/{id}/cleaning-report", response_model=DocumentCleaningReportResponse)
def get_cleaning_report(
    id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve the pipeline cleaning execution report metrics and warnings.
    Only the document owner may access this endpoint.
    """
    service = get_document_processing_service(db)
    doc_text = service.get_document_text(id, current_user.id)

    if not doc_text.cleaning_report_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cleaning report not available. Document text has not been cleaned yet.",
        )

    return DocumentCleaningReportResponse(
        document_id=doc_text.document_id,
        cleaning_version=doc_text.cleaning_version,
        cleaning_report=doc_text.cleaning_report_json,
        cleaning_processing_time=doc_text.cleaning_processing_time,
        updated_at=doc_text.updated_at,
    )


@router.get("/{id}/text-comparison", response_model=DocumentTextComparisonResponse)
def get_text_comparison(
    id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve a comparison of raw extracted text and cleaned text along with a difference summary.
    Only the document owner may access this endpoint.
    """
    service = get_document_processing_service(db)
    doc_text = service.get_document_text(id, current_user.id)

    # Try parsing the cleaning report to extract metrics
    summary = {}
    if doc_text.cleaning_report_json:
        try:
            summary = json.loads(doc_text.cleaning_report_json)
        except Exception:
            pass

    return DocumentTextComparisonResponse(
        document_id=doc_text.document_id,
        raw_text=doc_text.extracted_text,
        cleaned_text=doc_text.cleaned_text,
        summary=summary,
    )
