"""
app.document_processing.extractors.pdf_extractor — PDF file extractor.
"""

import time
import os
import logging
from typing import Callable, List, Optional
import fitz

from app.document_processing.extractors.base import AbstractDocumentExtractor, ExtractionResult
from app.document_processing.extractors.scanned_pdf_extractor import ScannedPDFExtractor
from app.document_processing.exceptions import ExtractionError, FileDecryptionError, CorruptedFileError

logger = logging.getLogger(__name__)

# Configurable character threshold. If digital text has fewer characters than this, fallback to OCR.
OCR_FALLBACK_CHAR_THRESHOLD = 100


class PDFExtractor(AbstractDocumentExtractor):
    """
    Parser for PDF documents.
    Attempts digital text extraction page-by-page. If text content is absent
    or below OCR_FALLBACK_CHAR_THRESHOLD, automatically triggers scanned PDF OCR.
    """

    def __init__(
        self,
        scanned_extractor: Optional[ScannedPDFExtractor] = None,
        char_threshold: int = OCR_FALLBACK_CHAR_THRESHOLD,
    ) -> None:
        self.scanned_extractor = scanned_extractor or ScannedPDFExtractor()
        self.char_threshold = char_threshold

    def can_handle(self, mime_type: str) -> bool:
        return mime_type == "application/pdf"

    def extract(
        self,
        file_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> ExtractionResult:
        start_time = time.time()

        if not os.path.exists(file_path):
            raise ExtractionError(f"File not found: {file_path}")

        try:
            doc = fitz.open(file_path)
        except Exception as exc:
            logger.error("Failed to open PDF file %s: %s", file_path, exc, exc_info=True)
            raise CorruptedFileError(f"PDF file is corrupted or unreadable: {exc}") from exc

        if doc.is_encrypted:
            doc.close()
            raise FileDecryptionError("PDF is password-protected or encrypted.")

        page_count = len(doc)
        if page_count == 0:
            doc.close()
            return ExtractionResult(
                extracted_text="",
                extraction_method="digital_pdf",
                page_count=0,
                processing_time=time.time() - start_time,
                confidence_score=1.0,
                has_ocr=False,
                success=True,
            )

        extracted_pages: List[str] = []
        metadata = {}

        # Capture PDF basic metadata properties
        try:
            meta = doc.metadata
            metadata = {
                "title": meta.get("title") or "",
                "author": meta.get("author") or "",
                "subject": meta.get("subject") or "",
                "keywords": meta.get("keywords") or "",
                "creator": meta.get("creator") or "",
                "producer": meta.get("producer") or "",
                "creation_date": meta.get("creationDate") or "",
                "mod_date": meta.get("modDate") or "",
                "page_count": page_count,
            }
        except Exception as exc:
            logger.warning("Failed to extract PDF metadata: %s", exc)

        # 1. Try digital text extraction first
        try:
            for page_num in range(page_count):
                page = doc.load_page(page_num)
                # get_text() extracts native PDF text structures
                page_text = page.get_text().strip()
                page_header = f"--- Page {page_num + 1} ---"
                extracted_pages.append(f"{page_header}\n\n{page_text}")
        except Exception as exc:
            logger.warning("Digital text extraction failed on page %d: %s. Falling back to OCR.", page_num + 1, exc)
            # Switch to OCR immediately
            doc.close()
            return self.scanned_extractor.extract(file_path, progress_callback)

        doc.close()

        # Combine text to evaluate character count
        full_text = "\n\n".join(extracted_pages)
        
        # Clean text character count calculation (exclude headers)
        clean_char_count = sum(len(p.split("\n\n", 1)[-1]) for p in extracted_pages if "\n\n" in p)

        # 2. Check if text is sparse or empty -> Trigger OCR Fallback
        if clean_char_count < self.char_threshold:
            logger.info(
                "PDF text sparse (%d characters). Triggering automatic OCR fallback.",
                clean_char_count,
            )
            return self.scanned_extractor.extract(file_path, progress_callback)

        # Successfully extracted digital PDF text
        processing_time = time.time() - start_time

        return ExtractionResult(
            extracted_text=full_text,
            extraction_method="digital_pdf",
            page_count=page_count,
            processing_time=processing_time,
            confidence_score=1.0,  # Digital text is 100% accurate relative to OCR
            has_ocr=False,
            metadata=metadata,
            warnings=[],
            success=True,
        )
