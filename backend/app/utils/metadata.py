import io
import os
from typing import Optional, Tuple
from pypdf import PdfReader
from PIL import Image
from app.models import DocumentCategory

def detect_category(filename: str, mime_type: Optional[str] = None) -> DocumentCategory:
    """
    Detect document category based on extension and mime type.
    """
    ext = ""
    if "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
    
    # Word formats
    if ext in {"doc", "docx"} or mime_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    }:
        return DocumentCategory.WORD
    
    # PDF
    if ext == "pdf" or mime_type == "application/pdf":
        return DocumentCategory.PDF
        
    # Text
    if ext == "txt" or mime_type == "text/plain":
        return DocumentCategory.TEXT
        
    # Image
    if ext in {"png", "jpg", "jpeg", "webp"} or (mime_type and mime_type.startswith("image/")):
        return DocumentCategory.IMAGE
        
    return DocumentCategory.OTHER


def extract_pdf_page_count(file_bytes: bytes) -> Optional[int]:
    """
    Safely extract page count from PDF file bytes using pypdf.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        return len(reader.pages)
    except Exception:
        return None


def extract_image_dimensions(file_bytes: bytes) -> Optional[Tuple[int, int]]:
    """
    Safely extract dimensions (width, height) from image bytes using Pillow.
    """
    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            return img.size
    except Exception:
        return None
