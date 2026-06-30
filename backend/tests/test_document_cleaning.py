"""
backend/tests/test_document_cleaning.py — Unit and integration tests for Phase 5.3 text cleaning pipeline.
"""

import io
import time
import uuid
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from main import app

from app.document_processing.cleaning.pipeline import DocumentTextCleaningPipeline
from app.document_processing.cleaning.strategies.unicode import UnicodeNormalizerStrategy
from app.document_processing.cleaning.strategies.whitespace import WhitespaceCleanupStrategy
from app.document_processing.cleaning.strategies.ocr_cleanup import OcrCleanupStrategy
from app.document_processing.cleaning.strategies.headers import HeaderRemovalStrategy
from app.document_processing.cleaning.strategies.footers import FooterRemovalStrategy
from app.document_processing.cleaning.strategies.page_numbers import PageNumberRemovalStrategy
from app.document_processing.cleaning.strategies.hyphenation import HyphenationRepairStrategy
from app.document_processing.cleaning.strategies.line_wrapping import LineWrappingRepairStrategy
from app.document_processing.cleaning.strategies.bullets import BulletNormalizationStrategy
from app.document_processing.cleaning.strategies.tables import TableFlatteningStrategy
from app.document_processing.cleaning.validators import validate_cleaned_text, CleaningValidationError


# ── 1. Unit Tests for Cleaning Strategies ──────────────────────────────────────

def test_unicode_normalizer():
    strategy = UnicodeNormalizerStrategy()
    text = "“Smart Quotes” and curly apostrophe’s — en-dash – em-dash—and spaces\xa0zero\u200bwidth."
    context = {}
    cleaned, context = strategy.clean(text, context)
    
    assert '"Smart Quotes"' in cleaned
    assert "apostrophe's" in cleaned
    assert "-" in cleaned
    assert "smart" not in cleaned.lower() or "“" not in cleaned
    assert "\xa0" not in cleaned
    assert "\u200b" not in cleaned
    assert context["whitespace_reductions"] > 0


def test_whitespace_cleanup():
    strategy = WhitespaceCleanupStrategy()
    text = "  Word   with  too    many   spaces.  \n\n\n\nNew paragraph.  "
    context = {}
    cleaned, context = strategy.clean(text, context)
    
    assert cleaned == "Word with too many spaces.\n\nNew paragraph."
    assert context["whitespace_reductions"] > 0


def test_ocr_cleanup():
    strategy = OcrCleanupStrategy()
    # Test duplicate punctuation
    text1 = "Duplicate commas,, colons:: semicolons;;"
    cleaned1, _ = strategy.clean(text1, {})
    assert ",," not in cleaned1
    assert "::" not in cleaned1
    assert ";;" not in cleaned1
    
    # Test noise lines
    text2 = "Line 1\n.........\n_______\nLine 2\n| Standalone pipe"
    cleaned2, _ = strategy.clean(text2, {})
    assert "........." not in cleaned2
    assert "_______" not in cleaned2
    assert "| Standalone" not in cleaned2
    assert "Standalone pipe" in cleaned2


def test_header_footer_removal():
    h_strategy = HeaderRemovalStrategy()
    f_strategy = FooterRemovalStrategy()
    
    # Multi-page text with repeating headers/footers
    page1 = "Supreme Court of India\nCase Brief Title\nBody of Page 1.\nCONFIDENTIAL FOOTER\n"
    page2 = "Supreme Court of India\nCase Brief Title\nBody of Page 2.\nCONFIDENTIAL FOOTER\n"
    page3 = "Supreme Court of India\nCase Brief Title\nBody of Page 3.\nCONFIDENTIAL FOOTER\n"
    
    text = f"--- Page 1 ---\n{page1}--- Page 2 ---\n{page2}--- Page 3 ---\n{page3}"
    
    context = {}
    # Clean headers
    cleaned, context = h_strategy.clean(text, context)
    assert "Supreme Court of India" not in cleaned
    assert "Case Brief Title" not in cleaned
    assert "Body of Page" in cleaned
    assert context["headers_removed"] >= 3
    
    # Clean footers
    cleaned_f, context_f = f_strategy.clean(cleaned, context)
    assert "CONFIDENTIAL FOOTER" not in cleaned_f
    assert context_f["footers_removed"] >= 3


def test_page_number_removal():
    strategy = PageNumberRemovalStrategy()
    text = "--- Page 1 ---\nPage 1\nBody text.\n1 of 35\n--- Page 2 ---\nPg. 2\nBody text 2.\n- 2 -\n"
    cleaned, context = strategy.clean(text, {})
    
    # Strip page markers to check if repeating page numbers themselves were removed
    text_no_markers = cleaned.replace("--- Page 1 ---", "").replace("--- Page 2 ---", "")
    assert "Page 1" not in text_no_markers
    assert "1 of 35" not in text_no_markers
    assert "Pg. 2" not in text_no_markers
    assert "- 2 -" not in text_no_markers
    assert "Body text" in cleaned
    assert context["page_numbers_removed"] >= 4


def test_hyphenation_repair():
    strategy = HyphenationRepairStrategy()
    # Test normal hyphenated wrap (merge)
    text1 = "This is a detailed investi-\ngation of the case."
    cleaned1, context1 = strategy.clean(text1, {})
    assert "investigation" in cleaned1
    assert "investi-" not in cleaned1
    assert context1["hyphen_repairs"] == 1
    
    # Test legitimate prefix hyphenation (preserve hyphen)
    text2 = "He suffers from a lack of self-\nesteem."
    cleaned2, context2 = strategy.clean(text2, {})
    assert "self-esteem" in cleaned2
    assert "selfesteem" not in cleaned2


def test_line_wrapping_repair():
    strategy = LineWrappingRepairStrategy()
    # Standard sentence wrapping
    text = "This is a line that wraps\nonto the next line, but it is\nthe same sentence.\n\nHere is a new paragraph."
    cleaned, _ = strategy.clean(text, {})
    assert "This is a line that wraps onto the next line, but it is the same sentence." in cleaned
    assert "\n\n" in cleaned
    
    # Do not merge lists/headings/numberings
    text2 = "Important list:\n  • First item\n  • Second item\n\n1. First number\n2. Second number"
    cleaned2, _ = strategy.clean(text2, {})
    assert "• First item" in cleaned2
    assert "• Second item" in cleaned2
    assert "1. First number" in cleaned2


def test_bullet_normalization():
    strategy = BulletNormalizationStrategy()
    text = "  - Bullet one\n  * Bullet two\n(a)    Excess spaces\n1.  Standard space"
    cleaned, context = strategy.clean(text, {})
    
    assert "  \u2022 Bullet one" in cleaned
    assert "  \u2022 Bullet two" in cleaned
    assert "(a) Excess spaces" in cleaned
    assert context["bullets_normalized"] == 4


def test_table_flattening():
    strategy = TableFlatteningStrategy()
    text = "Some text.\n| Name | Date | Court |\n|---|---|---|\n| John | 2026 | SC |\n| Mary | 2025 | HC |\nOther text."
    cleaned, context = strategy.clean(text, {})
    
    assert "--- Table Start ---" in cleaned
    assert "Row 1:" in cleaned
    assert "Name: John" in cleaned
    assert "Date: 2026" in cleaned
    assert "Court: SC" in cleaned
    assert "Row 2:" in cleaned
    assert "--- Table End ---" in cleaned
    assert context["tables_flattened"] == 1


# ── 2. Validation Tests ────────────────────────────────────────────────────────

def test_validators():
    # Blank output
    with pytest.raises(CleaningValidationError):
        validate_cleaned_text("Input", "")
    
    # Character count validation (triggered when input is > 100 characters and ratio is < 20%)
    with pytest.raises(CleaningValidationError):
        validate_cleaned_text("A very long original document text block. " * 5, "Short")
    
    # Paragraph integrity validation
    with pytest.raises(CleaningValidationError):
        validate_cleaned_text("Para 1\n\nPara 2\n\nPara 3\n\nPara 4", "Para 1 Para 2 Para 3 Para 4")


# ── 3. Pipeline Integration Tests ──────────────────────────────────────────────

def test_pipeline_execution():
    pipeline = DocumentTextCleaningPipeline()
    messy_text = (
        "--- Page 1 ---\n"
        "Supreme Court Brief\n"
        "Case No. 12345\n"
        "  - Paragraph wrap testi-\n"
        "ng curly \u201cquotes\u201d and double,, commas.\n"
        "Page 1\n"
        "--- Page 2 ---\n"
        "Supreme Court Brief\n"
        "Case No. 12345\n"
        "We are cite Article 21 and Section 302 IPC here.\n"
        "Page 2\n"
    )
    
    cleaned, report = pipeline.clean_text(messy_text, "pdf")
    
    assert "testing" in cleaned
    assert '"quotes"' in cleaned
    assert "Supreme Court Brief" not in cleaned  # Stripped as repeating header
    assert "Case No. 12345" not in cleaned      # Stripped as repeating header
    
    text_no_markers = cleaned.replace("--- Page 1 ---", "").replace("--- Page 2 ---", "")
    assert "Page 1" not in text_no_markers              # Stripped as page number
    assert "Article 21" in cleaned              # Preserved citation
    assert "Section 302 IPC" in cleaned          # Preserved citation
    assert report["version"] == "1.0.0"


# ── 4. API Endpoint Integration Tests ─────────────────────────────────────────

from fastapi.testclient import TestClient

def _register_and_login(client: TestClient) -> dict:
    uid = uuid.uuid4().hex[:8]
    email = f"cleaner{uid}@example.com"
    client.post("/api/auth/register", json={
        "email": email,
        "username": f"cleaner{uid}",
        "password": "password123",
        "full_name": "Text Cleaner",
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_case(client: TestClient, headers: dict) -> dict:
    r = client.post("/api/cases", json={"title": "Cleaning Case"}, headers=headers)
    return r.json()


def _upload_document(client: TestClient, headers: dict, case_id: str) -> str:
    files = {"file": ("brief.txt", io.BytesIO(b"Messy text brief testing."), "text/plain")}
    data = {"title": "Cleaning Document", "case_id": case_id}
    resp = client.post("/api/documents/upload", files=files, data=data, headers=headers)
    return resp.json()["id"]


def test_api_cleaning_endpoints():
    with TestClient(app) as test_client:
        headers = _register_and_login(test_client)
        case = _create_case(test_client, headers)
        doc_id = _upload_document(test_client, headers, case["id"])

        # Trigger processing job creation
        job_resp = test_client.post("/api/processing/jobs", json={
            "document_id": doc_id,
            "job_type": "text_extraction",
        }, headers=headers)
        assert job_resp.status_code == 201

        # Wait briefly for worker task loop
        time.sleep(3.0)

        # 1. Fetch cleaned text
        cleaned_resp = test_client.get(f"/api/documents/{doc_id}/cleaned-text", headers=headers)
        assert cleaned_resp.status_code == 200
        cleaned_data = cleaned_resp.json()
        assert "cleaned_text" in cleaned_data
        assert "testing" in cleaned_data["cleaned_text"]
        assert cleaned_data["cleaning_version"] == "1.0.0"

        # 2. Fetch cleaning report
        report_resp = test_client.get(f"/api/documents/{doc_id}/cleaning-report", headers=headers)
        assert report_resp.status_code == 200
        report_data = report_resp.json()
        assert "cleaning_report" in report_data
        assert report_data["cleaning_version"] == "1.0.0"

        # 3. Fetch text comparison
        compare_resp = test_client.get(f"/api/documents/{doc_id}/text-comparison", headers=headers)
        assert compare_resp.status_code == 200
        compare_data = compare_resp.json()
        assert "raw_text" in compare_data
        assert "cleaned_text" in compare_data
        assert "summary" in compare_data
