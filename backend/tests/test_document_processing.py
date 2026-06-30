"""
Unit and integration tests for document extraction pipeline (Phase 5.2).
"""

import io
import uuid
import time
import os
import json
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from app.document_processing.exceptions import ExtractionError, UnsupportedFileTypeError
from app.document_processing.extractors.base import ExtractionResult
from app.document_processing.extractors.txt_extractor import TxtExtractor
from app.document_processing.extractors.docx_extractor import DocxExtractor
from app.document_processing.extractors.image_extractor import ImageExtractor
from app.document_processing.extractors.pdf_extractor import PDFExtractor
from app.document_processing.pipeline import DocumentProcessingPipeline
from app.document_processing.ocr.ocr_engine import TesseractEngine
from app.document_processing.ocr.image_preprocessing import preprocess_image

# ── 1. Unit Tests for TXT Extractor ───────────────────────────────────────────

def test_txt_extractor_utf8(tmp_path):
    txt_file = tmp_path / "test.txt"
    content = "Hello ChronoLegal Document Extraction!"
    txt_file.write_text(content, encoding="utf-8")

    extractor = TxtExtractor()
    assert extractor.can_handle("text/plain") is True

    result = extractor.extract(str(txt_file))
    assert result.success is True
    assert result.extracted_text == content
    assert result.extraction_method == "txt"
    assert result.metadata["encoding"] == "utf-8"


def test_txt_extractor_utf16(tmp_path):
    txt_file = tmp_path / "test_utf16.txt"
    content = "Legal text with special glyphs."
    txt_file.write_bytes(content.encode("utf-16"))

    extractor = TxtExtractor()
    result = extractor.extract(str(txt_file))
    assert result.success is True
    assert result.extracted_text == content
    assert result.metadata["encoding"] == "utf-16"


def test_txt_extractor_latin1_fallback(tmp_path):
    txt_file = tmp_path / "test_latin1.txt"
    content = "Some characters: \xe1\xe9\xed\xf3\xfa\xf1."
    txt_file.write_bytes(content.encode("latin-1"))

    extractor = TxtExtractor()
    result = extractor.extract(str(txt_file))
    assert result.success is True
    assert result.extracted_text == content
    assert result.metadata["encoding"] == "latin-1"
    assert len(result.warnings) > 0


# ── 2. Unit Tests for Image & OCR Extractor ───────────────────────────────────

@patch("pytesseract.image_to_string")
@patch("pytesseract.image_to_data")
def test_image_extractor_ocr(mock_image_to_data, mock_image_to_string, tmp_path):
    # Mock Tesseract outputs
    mock_image_to_string.return_value = "Extracted OCR Text from PNG Image"
    mock_image_to_data.return_value = {
        "text": ["Extracted", "OCR", "Text"],
        "conf": ["95.0", "90.0", "92.0"],
    }

    img_file = tmp_path / "test.png"
    # Save a small blank image
    img = Image.new("RGB", (100, 100), color="white")
    img.save(img_file)

    extractor = ImageExtractor()
    assert extractor.can_handle("image/png") is True

    result = extractor.extract(str(img_file))
    assert result.success is True
    assert result.extracted_text == "Extracted OCR Text from PNG Image"
    assert result.extraction_method == "image_ocr"
    assert result.has_ocr is True
    # Normalized confidence score: (95 + 90 + 92) / 3 / 100 = 0.9233...
    assert 0.9 < result.confidence_score <= 1.0


# ── 3. Unit Tests for Image Preprocessing ──────────────────────────────────────

def test_image_preprocessing():
    # Verify Pillow preprocessing transforms modes correctly
    img = Image.new("RGB", (200, 200), color="red")
    processed = preprocess_image(img, enhance_contrast=False, binarize=False)
    assert processed.mode == "L"  # Grayscale

    binarized = preprocess_image(img, binarize=True)
    assert binarized.mode == "1"  # Black and White thresholded


# ── 4. Unit Tests for PDF Extractor ───────────────────────────────────────────

@patch("app.document_processing.extractors.pdf_extractor.os.path.exists")
@patch("fitz.open")
def test_pdf_extractor_digital(mock_fitz_open, mock_exists):
    mock_exists.return_value = True
    
    # Setup PyMuPDF mock document
    mock_doc = MagicMock()
    mock_doc.is_encrypted = False
    mock_doc.metadata = {"title": "Test Brief"}
    
    mock_page = MagicMock()
    mock_page.get_text.return_value = "This is digital PDF text content."
    mock_doc.__len__.return_value = 1
    mock_doc.load_page.return_value = mock_page
    
    mock_fitz_open.return_value = mock_doc

    # Set low char_threshold so 33 chars doesn't trigger OCR fallback
    extractor = PDFExtractor(char_threshold=5)
    assert extractor.can_handle("application/pdf") is True

    result = extractor.extract("fake_path.pdf")
    assert result.success is True
    assert result.extraction_method == "digital_pdf"
    assert "This is digital PDF text content." in result.extracted_text
    assert result.has_ocr is False
    assert result.page_count == 1
    assert result.metadata["title"] == "Test Brief"


# ── 5. Integration Tests: Pipeline & Worker ───────────────────────────────────

def test_pipeline_routing():
    # Verify unsupported type raises error
    pipeline = DocumentProcessingPipeline()
    with pytest.raises(UnsupportedFileTypeError):
        pipeline.process_document("file.exe", declared_mime="application/x-msdownload")


# ── 6. API Endpoint Integration Tests ─────────────────────────────────────────

from fastapi.testclient import TestClient
from main import app

def _register_and_login(client: TestClient) -> dict:
    uid = uuid.uuid4().hex[:8]
    email = f"ocrtest{uid}@example.com"
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"ocrtest{uid}",
        "password": "password123",
        "full_name": "OCR Tester",
    })
    assert reg.status_code == 201, reg.text
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_case(client: TestClient, headers: dict) -> dict:
    r = client.post("/api/cases", json={"title": "OCR Case"}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _upload_document(client: TestClient, headers: dict, case_id: str, content: bytes, filename: str, mime: str) -> str:
    files = {"file": (filename, io.BytesIO(content), mime)}
    data = {"title": "OCR Document", "case_id": case_id}
    resp = client.post("/api/documents/upload", files=files, data=data, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_extracted_text_endpoints():
    with TestClient(app) as test_client:
        headers = _register_and_login(test_client)
        case = _create_case(test_client, headers)
        
        # Upload a TXT file
        text_content = b"Legal case contract detail text record."
        doc_id = _upload_document(test_client, headers, case["id"], text_content, "contract.txt", "text/plain")

        # Initially, GET text returns 404 because worker has not run yet
        resp = test_client.get(f"/api/documents/{doc_id}/text", headers=headers)
        assert resp.status_code == 404

        # Trigger background job creation
        job_resp = test_client.post("/api/processing/jobs", json={
            "document_id": doc_id,
            "job_type": "text_extraction",
        }, headers=headers)
        assert job_resp.status_code == 201
        job_id = job_resp.json()["id"]

        # Wait briefly for worker task loop to process the queue job
        time.sleep(2.5)

        # Re-retrieve text record
        resp_text = test_client.get(f"/api/documents/{doc_id}/text", headers=headers)
        assert resp_text.status_code == 200
        text_data = resp_text.json()
        assert "Legal case contract detail text record." in text_data["extracted_text"]
        assert text_data["extraction_method"] == "txt"

        # Verify metadata endpoint
        resp_meta = test_client.get(f"/api/documents/{doc_id}/metadata", headers=headers)
        assert resp_meta.status_code == 200
        meta_data = resp_meta.json()
        assert meta_data["metadata"]["encoding"] == "utf-8"

        # Verify preview text endpoint
        resp_prev = test_client.get(f"/api/documents/{doc_id}/preview-text", headers=headers)
        assert resp_prev.status_code == 200
        prev_data = resp_prev.json()
        assert "preview_text" in prev_data
        assert len(prev_data["preview_text"]) <= 1000
