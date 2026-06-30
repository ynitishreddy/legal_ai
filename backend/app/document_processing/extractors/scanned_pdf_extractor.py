"""
app.document_processing.extractors.scanned_pdf_extractor — Scanned PDF OCR extractor.
"""

import time
import os
import io
import logging
from typing import Callable, List, Optional
from PIL import Image
import fitz

from app.document_processing.extractors.base import AbstractDocumentExtractor, ExtractionResult
from app.document_processing.exceptions import ExtractionError, FileDecryptionError, CorruptedFileError
from app.document_processing.ocr.ocr_engine import TesseractEngine
from app.document_processing.ocr.image_preprocessing import preprocess_image

logger = logging.getLogger(__name__)


class ScannedPDFExtractor(AbstractDocumentExtractor):
    """
    Parser for scanned PDFs.
    Renders PDF pages directly to in-memory PNG pixmaps using PyMuPDF (fitz),
    preprocesses each page image, and runs Tesseract OCR.
    Supports a progress callback to track multi-page OCR updates.
    """

    def __init__(self, ocr_engine: Optional[TesseractEngine] = None) -> None:
        self.ocr_engine = ocr_engine or TesseractEngine()

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
            logger.error("PyMuPDF failed to open PDF file: %s", exc, exc_info=True)
            raise CorruptedFileError(f"PDF file is corrupted or unreadable: {exc}") from exc

        if doc.is_encrypted:
            doc.close()
            raise FileDecryptionError("PDF is password-protected or encrypted.")

        page_count = len(doc)
        if page_count == 0:
            doc.close()
            return ExtractionResult(
                extracted_text="",
                extraction_method="ocr_pdf",
                page_count=0,
                processing_time=time.time() - start_time,
                confidence_score=1.0,
                has_ocr=True,
                success=True,
            )

        extracted_pages: List[str] = []
        confidences: List[float] = []
        warnings: List[str] = []

        try:
            for page_num in range(page_count):
                if progress_callback:
                    progress_callback(page_num + 1, page_count)

                logger.info("ScannedPDFExtractor: OCR page %d of %d", page_num + 1, page_count)
                
                # 1. Render page to image in memory at 150 DPI
                page = doc.load_page(page_num)
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("png")
                
                with Image.open(io.BytesIO(img_bytes)) as pil_img:
                    # 2. Preprocess page image
                    preprocessed = preprocess_image(
                        pil_img,
                        enhance_contrast=True,
                        binarize=True,
                        remove_noise=True,
                        normalize_dpi=False,  # Already at 150 DPI
                    )

                    # 3. Perform OCR
                    text, conf = self.ocr_engine.perform_ocr(preprocessed)
                    
                    page_header = f"--- Page {page_num + 1} ---"
                    extracted_pages.append(f"{page_header}\n\n{text}")
                    confidences.append(conf)

        except Exception as exc:
            logger.error("OCR execution error on PDF page %d: %s", page_num + 1, exc, exc_info=True)
            warnings.append(f"Failed to run OCR on page {page_num + 1}: {exc}")
            # If some pages succeeded, we want to return what we have, otherwise raise
            if not extracted_pages:
                doc.close()
                raise ExtractionError(f"Scanned PDF OCR failed: {exc}") from exc
        finally:
            doc.close()

        full_text = "\n\n".join(extracted_pages)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        processing_time = time.time() - start_time

        # Extract pdf basic metadata properties
        metadata = {
            "page_count": page_count,
            "dpi": 150,
        }

        return ExtractionResult(
            extracted_text=full_text,
            extraction_method="ocr_pdf",
            page_count=page_count,
            processing_time=processing_time,
            confidence_score=avg_confidence,
            has_ocr=True,
            metadata=metadata,
            warnings=warnings,
            success=True,
        )
