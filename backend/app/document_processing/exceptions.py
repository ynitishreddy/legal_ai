"""
app.document_processing.exceptions — Extraction and OCR exceptions.
"""

class ExtractionError(Exception):
    """Base exception for all document extraction errors."""
    pass


class UnsupportedFileTypeError(ExtractionError):
    """Raised when a file type is not supported by any extractor."""
    pass


class OCREngineError(ExtractionError):
    """Base exception for all OCR errors."""
    pass


class TesseractNotInstalledError(OCREngineError):
    """Raised when the tesseract binary is not installed or configured."""
    pass


class CorruptedFileError(ExtractionError):
    """Raised when file parser reports that the file format is corrupt or unreadable."""
    pass


class FileDecryptionError(ExtractionError):
    """Raised when a file (e.g. PDF) is password-protected or encrypted and cannot be read."""
    pass
