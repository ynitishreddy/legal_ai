"""
app.document_processing.ocr.ocr_engine — Abstract OCR engine interface and Tesseract implementation.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional
from PIL import Image

import pytesseract

from app.core.config import get_settings
from app.document_processing.exceptions import TesseractNotInstalledError

logger = logging.getLogger(__name__)


class AbstractOCREngine(ABC):
    """
    Abstract interface for OCR engines.
    Swappable with other engines (e.g. AWS Textract, Google Cloud Vision, EasyOCR) in the future.
    """

    @abstractmethod
    def perform_ocr(self, image: Image.Image) -> tuple[str, float]:
        """
        Extract text from an image and return (extracted_text, confidence_score_0_to_1).
        """


class TesseractEngine(AbstractOCREngine):
    """
    OCR Engine using pytesseract.
    Retrieves path settings from core config settings.tesseract_cmd.
    """

    def __init__(self) -> None:
        settings = get_settings()
        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
            logger.info("TesseractEngine: Set binary path to %s", settings.tesseract_cmd)
        else:
            logger.debug("TesseractEngine: Using default tesseract path")

    def perform_ocr(self, image: Image.Image) -> tuple[str, float]:
        """
        Execute OCR on the PIL Image.
        Returns:
            tuple[str, float]: (extracted text with formatting, average confidence score normalized 0.0-1.0)
        """
        try:
            # 1. Run image_to_string to get text with layout preserved
            text = pytesseract.image_to_string(image)

            # 2. Run image_to_data to calculate average confidence
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            
            confidences = []
            if "conf" in data and "text" in data:
                for i in range(len(data["text"])):
                    word = data["text"][i].strip()
                    conf = float(data["conf"][i])
                    # Tesseract puts conf = -1 for white space or bounding boxes without text
                    if word and conf >= 0:
                        confidences.append(conf)

            avg_conf = sum(confidences) / len(confidences) if confidences else 100.0
            normalized_conf = max(0.0, min(1.0, avg_conf / 100.0))

            return text, normalized_conf

        except pytesseract.TesseractNotFoundError as exc:
            logger.error("Tesseract binary not found. Please install Tesseract and configure TESSERACT_CMD.", exc_info=True)
            raise TesseractNotInstalledError(
                "Tesseract OCR is not installed or configured correctly on this system. "
                "Ensure Tesseract is installed and configured in your settings."
            ) from exc
        except Exception as exc:
            logger.error("Error executing Tesseract OCR on image: %s", exc, exc_info=True)
            raise TesseractNotInstalledError(f"OCR execution failed: {exc}") from exc
