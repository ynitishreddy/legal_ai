"""
app.document_processing.extractors.image_extractor — Image OCR file extractor.
"""

import time
import os
import logging
from typing import Optional
from PIL import Image

from app.document_processing.extractors.base import AbstractDocumentExtractor, ExtractionResult
from app.document_processing.exceptions import ExtractionError
from app.document_processing.ocr.ocr_engine import TesseractEngine
from app.document_processing.ocr.image_preprocessing import preprocess_image

logger = logging.getLogger(__name__)


class ImageExtractor(AbstractDocumentExtractor):
    """
    Parser for image files (PNG, JPEG, JPG, TIFF, BMP, WEBP).
    Loads via Pillow, applies preprocessing filters, and runs Tesseract OCR.
    """

    def __init__(self, ocr_engine: Optional[TesseractEngine] = None) -> None:
        self.ocr_engine = ocr_engine or TesseractEngine()

    def can_handle(self, mime_type: str) -> bool:
        return mime_type in {
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/tiff",
            "image/bmp",
            "image/webp",
        } or mime_type.startswith("image/")

    def extract(self, file_path: str) -> ExtractionResult:
        start_time = time.time()

        if not os.path.exists(file_path):
            raise ExtractionError(f"File not found: {file_path}")

        try:
            with Image.open(file_path) as img:
                # Capture metadata of original image
                width, height = img.size
                dpi = img.info.get("dpi", (72, 72))
                color_mode = img.mode

                metadata = {
                    "width": width,
                    "height": height,
                    "dpi": list(dpi) if isinstance(dpi, tuple) else dpi,
                    "color_mode": color_mode,
                }

                # Apply preprocessing pipeline to maximize OCR accuracy
                preprocessed = preprocess_image(
                    img,
                    enhance_contrast=True,
                    binarize=True,
                    remove_noise=True,
                    normalize_dpi=True,
                )

                # Perform OCR
                logger.info("ImageExtractor: Running OCR on image file %s", file_path)
                text, confidence = self.ocr_engine.perform_ocr(preprocessed)

        except Exception as exc:
            logger.error("Failed to run image extraction on %s: %s", file_path, exc, exc_info=True)
            raise ExtractionError(f"Image OCR extraction failed: {exc}") from exc

        processing_time = time.time() - start_time

        return ExtractionResult(
            extracted_text=text,
            extraction_method="image_ocr",
            page_count=1,
            processing_time=processing_time,
            confidence_score=confidence,
            has_ocr=True,
            metadata=metadata,
            warnings=[],
            success=True,
        )
