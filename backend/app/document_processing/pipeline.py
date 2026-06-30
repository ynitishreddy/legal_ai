"""
app.document_processing.pipeline — Document processing pipeline.

Orchestrates MIME-detection and executes the appropriate extractor strategy.
"""

import logging
from typing import Callable, List, Optional
from uuid import UUID

from app.document_processing.exceptions import UnsupportedFileTypeError
from app.document_processing.utils import detect_mime_type
from app.document_processing.extractors.base import AbstractDocumentExtractor, ExtractionResult
from app.document_processing.extractors.pdf_extractor import PDFExtractor
from app.document_processing.extractors.docx_extractor import DocxExtractor
from app.document_processing.extractors.txt_extractor import TxtExtractor
from app.document_processing.extractors.image_extractor import ImageExtractor

logger = logging.getLogger(__name__)


class DocumentProcessingPipeline:
    """
    Main orchestration pipeline for case document text extraction.
    Registers multiple extractors and routes incoming documents to the matching strategy.
    """

    def __init__(self, extractors: Optional[List[AbstractDocumentExtractor]] = None) -> None:
        if extractors is not None:
            self.extractors = extractors
        else:
            # Default production extractor strategies
            self.extractors = [
                PDFExtractor(),
                DocxExtractor(),
                TxtExtractor(),
                ImageExtractor(),
            ]

    def process_document(
        self,
        file_path: str,
        declared_mime: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> ExtractionResult:
        """
        Detect file type, select the matching extractor strategy, and run text extraction.
        """
        # 1. Detect MIME type
        mime_type = detect_mime_type(file_path, declared_mime)
        logger.info("Pipeline: Processing file=%s resolved_mime=%s", file_path, mime_type)

        # 2. Select extractor strategy
        matching_extractor: Optional[AbstractDocumentExtractor] = None
        for extractor in self.extractors:
            if extractor.can_handle(mime_type):
                matching_extractor = extractor
                break

        if not matching_extractor:
            logger.error("Pipeline: No extractor found for MIME type %s", mime_type)
            raise UnsupportedFileTypeError(f"Unsupported file format: {mime_type}")

        # 3. Extract raw text
        logger.info("Pipeline: Selected extractor strategy %s", matching_extractor.__class__.__name__)
        
        # Pass progress_callback to PDF extractors if supported in signature
        if isinstance(matching_extractor, PDFExtractor):
            result = matching_extractor.extract(file_path, progress_callback)
        else:
            result = matching_extractor.extract(file_path)

        return result


# ── Global pipeline singleton ─────────────────────────────────────────────────

document_processing_pipeline: DocumentProcessingPipeline = DocumentProcessingPipeline()
