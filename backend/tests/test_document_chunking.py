"""
backend/tests/test_document_chunking.py — Unit and integration tests for Phase 5.4 chunking pipeline.
"""

import io
import time
import uuid
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient
from main import app

from app.document_processing.chunking.schemas import ChunkingConfig
from app.document_processing.chunking.strategies.paragraph_chunker import ParagraphChunkingStrategy
from app.document_processing.chunking.strategies.sliding_window_chunker import SlidingWindowChunkingStrategy
from app.document_processing.chunking.strategies.heading_chunker import HeadingAwareChunkingStrategy
from app.document_processing.chunking.strategies.legal_chunker import LegalSectionChunkingStrategy
from app.document_processing.chunking.validator import validate_chunks, ChunkingValidationError
from app.document_processing.chunking.pipeline import document_chunking_pipeline
from app.document_processing.chunking.service import get_document_chunking_service


# ── 1. Unit Tests for Chunking Strategies ──────────────────────────────────────

def test_paragraph_chunking():
    strategy = ParagraphChunkingStrategy()
    text = "Paragraph one is normal text.\n\nParagraph two is another normal text block.\n\nParagraph three is the final paragraph."
    config = ChunkingConfig(max_characters=100, max_words=20, min_chunk_size=10)
    
    chunks = strategy.chunk(text, config)
    # Should divide paragraphs since they exceed max characters combined
    assert len(chunks) >= 2
    assert chunks[0].word_count > 0
    assert chunks[0].page_start == 1


def test_sliding_window_chunking():
    strategy = SlidingWindowChunkingStrategy()
    text = "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five."
    # Max words = 10, overlap = 2
    config = ChunkingConfig(max_words=8, overlap_size=2, min_chunk_size=5)
    
    chunks = strategy.chunk(text, config)
    assert len(chunks) >= 2
    # Ensure adjacent overlap words exist
    assert "Sentence" in chunks[0].text
    assert "Sentence" in chunks[1].text


def test_heading_aware_chunking():
    strategy = HeadingAwareChunkingStrategy()
    text = "### FACTS\nThis is paragraph under facts.\n\n### ISSUES\nThese are issues under consideration."
    config = ChunkingConfig()
    
    chunks = strategy.chunk(text, config)
    assert len(chunks) >= 2
    assert chunks[0].section_title == "FACTS"
    assert chunks[1].section_title == "ISSUES"


def test_legal_section_chunking():
    strategy = LegalSectionChunkingStrategy()
    text = "FACTS OF THE CASE\nThis represents the statement of facts.\n\nISSUES FOR CONSIDERATION\nPoint 1. Point 2.\n\nFINDINGS\nThe court holds that..."
    config = ChunkingConfig()
    
    chunks = strategy.chunk(text, config)
    assert len(chunks) >= 3
    assert chunks[0].section_title == "Facts"
    assert chunks[1].section_title == "Issues"
    assert chunks[2].section_title == "Findings"


# ── 2. Validation Tests ────────────────────────────────────────────────────────

def test_chunk_validators():
    config = ChunkingConfig(min_chunk_size=20, max_characters=200)
    
    # 1. Empty list
    with pytest.raises(ChunkingValidationError):
        validate_chunks([], config)
        
    # 2. Too small chunk
    from app.document_processing.chunking.schemas import ChunkResult
    bad_chunk = ChunkResult(
        text="Short", page_start=1, page_end=1, paragraph_start=1, paragraph_end=1,
        word_count=1, character_count=5, estimated_tokens=1
    )
    with pytest.raises(ChunkingValidationError):
        validate_chunks([bad_chunk], config)

    # 3. Oversized chunk
    giant_chunk = ChunkResult(
        text="A" * 500, page_start=1, page_end=1, paragraph_start=1, paragraph_end=1,
        word_count=50, character_count=500, estimated_tokens=70
    )
    with pytest.raises(ChunkingValidationError):
        validate_chunks([giant_chunk], config)


# ── 3. Pipeline & Service Integration Tests ────────────────────────────────────

def test_pipeline_execution():
    text = "--- Page 1 ---\nFACTS OF THE CASE\nFirst sentence of facts.\n\n--- Page 2 ---\nFINDINGS\nWe present the findings."
    chunks, report, strategy = document_chunking_pipeline.generate_chunks(text, "judgment")
    
    assert len(chunks) >= 2
    assert report["total_chunks"] == len(chunks)
    assert report["strategy_used"] == "LegalSectionChunkingStrategy"
    
    # Filter out empty or introductory chunks if any
    non_intro_chunks = [c for c in chunks if c.section_title != "Introductory Context"]
    assert len(non_intro_chunks) >= 2
    assert non_intro_chunks[0].section_title == "Facts"
    assert non_intro_chunks[0].page_start == 1
    assert non_intro_chunks[1].section_title == "Findings"
    assert non_intro_chunks[1].page_start == 2



# ── 4. API Endpoints Integration Tests ─────────────────────────────────────────

def _register_and_login(client: TestClient) -> dict:
    uid = uuid.uuid4().hex[:8]
    email = f"chunker{uid}@example.com"
    client.post("/api/auth/register", json={
        "email": email,
        "username": f"chunker{uid}",
        "password": "password123",
        "full_name": "Text Chunker",
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_case(client: TestClient, headers: dict) -> dict:
    r = client.post("/api/cases", json={"title": "Chunking Case"}, headers=headers)
    return r.json()


def _upload_document(client: TestClient, headers: dict, case_id: str) -> str:
    files = {"file": ("judgment.txt", io.BytesIO(b"FACTS OF THE CASE\nThis is normal legal fact line on page 1.\n\nISSUES FOR CONSIDERATION\nThis is page 2."), "text/plain")}
    data = {"title": "Chunking Document", "case_id": case_id}
    resp = client.post("/api/documents/upload", files=files, data=data, headers=headers)
    return resp.json()["id"]


def test_api_chunking_endpoints():
    with TestClient(app) as test_client:
        headers = _register_and_login(test_client)
        case = _create_case(test_client, headers)
        doc_id = _upload_document(test_client, headers, case["id"])

        # Trigger background pipeline
        job_resp = test_client.post("/api/processing/jobs", json={
            "document_id": doc_id,
            "job_type": "text_extraction",
        }, headers=headers)
        assert job_resp.status_code == 201

        # Wait briefly for execution
        time.sleep(3.0)

        # 1. Fetch chunks list
        chunks_resp = test_client.get(f"/api/documents/{doc_id}/chunks", headers=headers)
        assert chunks_resp.status_code == 200
        chunks_data = chunks_resp.json()
        assert len(chunks_data) >= 1
        chunk_id = chunks_data[0]["id"]
        assert chunks_data[0]["chunk_text"] != ""

        # 2. Fetch specific chunk details
        detail_resp = test_client.get(f"/api/documents/{doc_id}/chunks/{chunk_id}", headers=headers)
        assert detail_resp.status_code == 200
        assert detail_resp.json()["id"] == chunk_id

        # 3. Fetch statistics
        stats_resp = test_client.get(f"/api/documents/{doc_id}/chunk-stats", headers=headers)
        assert stats_resp.status_code == 200
        stats_data = stats_resp.json()
        assert stats_data["total_chunks"] >= 1
        assert stats_data["average_chunk_size"] > 0

        # 4. Fetch boundaries preview
        preview_resp = test_client.get(f"/api/documents/{doc_id}/chunk-preview", headers=headers)
        assert preview_resp.status_code == 200
        preview_data = preview_resp.json()
        assert len(preview_data["boundaries"]) >= 1
        assert preview_data["boundaries"][0]["chunk_index"] == 0
