"""
app.document_processing.extractors.txt_extractor — Simple text file extractor.
"""

import time
import os
import logging
from app.document_processing.extractors.base import AbstractDocumentExtractor, ExtractionResult
from app.document_processing.exceptions import ExtractionError

logger = logging.getLogger(__name__)


class TxtExtractor(AbstractDocumentExtractor):
    """
    Parser for simple plain text files (.txt).
    Tolerates and detects multiple encodings: UTF-8, UTF-16, and Latin-1 fallback.
    """

    def can_handle(self, mime_type: str) -> bool:
        return mime_type in {"text/plain", "application/octet-stream"} or mime_type.startswith("text/")

    def extract(self, file_path: str) -> ExtractionResult:
        start_time = time.time()
        
        if not os.path.exists(file_path):
            raise ExtractionError(f"File not found: {file_path}")

        encodings = ["utf-8", "utf-16", "latin-1"]
        text = ""
        used_encoding = None
        warnings = []

        with open(file_path, "rb") as f:
            raw_bytes = f.read()

        # Check for UTF-16 BOM signature
        if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
            try:
                text = raw_bytes.decode("utf-16")
                used_encoding = "utf-16"
            except UnicodeDecodeError:
                pass

        # If not UTF-16 or UTF-16 decode failed, try UTF-8 then Latin-1
        if not used_encoding:
            for enc in ["utf-8", "latin-1"]:
                try:
                    text = raw_bytes.decode(enc)
                    used_encoding = enc
                    break
                except UnicodeDecodeError:
                    continue

        if used_encoding is None:
            raise ExtractionError("Failed to decode text file. Unsupported file encoding.")

        if used_encoding == "latin-1":
            warnings.append("File decoded using Latin-1 fallback. Some special characters may be garbled.")

        processing_time = time.time() - start_time
        
        # Text file metadata
        file_size = len(raw_bytes)
        metadata = {
            "encoding": used_encoding,
            "file_size": file_size,
        }

        return ExtractionResult(
            extracted_text=text,
            extraction_method="txt",
            page_count=1,
            processing_time=processing_time,
            confidence_score=1.0,
            has_ocr=False,
            metadata=metadata,
            warnings=warnings,
            success=True,
        )
