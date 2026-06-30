"""
app.document_processing.extractors.base — Abstract base extractor and ExtractionResult class.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ExtractionResult(BaseModel):
    """
    Standardized payload returned by all document extractors.
    """
    extracted_text: str = Field(..., description="The complete raw text extracted from the document")
    extraction_method: str = Field(..., description="E.g., digital_pdf, ocr_pdf, docx, txt, image_ocr")
    page_count: int = Field(default=1, ge=0)
    processing_time: float = Field(default=0.0, description="Time spent in seconds")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    has_ocr: bool = Field(default=False)
    language_detected: Optional[str] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary file-specific metadata")
    warnings: List[str] = Field(default_factory=list)
    success: bool = Field(default=True)


class AbstractDocumentExtractor(ABC):
    """
    Abstract strategy class for document extractors.
    All supported file parsers must inherit from this class.
    """

    @abstractmethod
    def can_handle(self, mime_type: str) -> bool:
        """
        Return True if this extractor can parse a file with the given MIME type.
        """

    @abstractmethod
    def extract(self, file_path: str) -> ExtractionResult:
        """
        Parse the file and return a standardized ExtractionResult.
        """
