"""
app.document_processing.utils — Document processing utility functions.
"""

import mimetypes
from typing import Optional

# Standard MIME type mappings for supported extension fallback
_EXT_MIME_MAPPINGS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}


def detect_mime_type(file_path: str, declared_mime: Optional[str] = None) -> str:
    """
    Detect the MIME type of a document file.
    Uses Python's mimetypes module first, and falls back to extension mappings
    if it cannot be resolved.
    """
    if declared_mime and declared_mime != "application/octet-stream":
        return declared_mime

    # Resolve from path extension
    mime, _ = mimetypes.guess_type(file_path)
    if mime:
        return mime

    # Manual fallback check
    _, ext = os_ext = file_path.rsplit(".", 1) if "." in file_path else ("", "")
    ext = f".{ext.lower()}"
    return _EXT_MIME_MAPPINGS.get(ext, "application/octet-stream")
