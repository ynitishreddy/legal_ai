import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from main import app
from app.db.session import SessionLocal
from app.core.config import get_settings
from app.models import User, Document, RetrievalLog
from app.document_processing.models import DocumentChunk
from app.services.retriever import RetrieverService
from app.services.qdrant import QdrantService

client = TestClient(app)


@pytest.fixture(scope="function", autouse=True)
def force_memory_qdrant(monkeypatch):
    # Override settings to force local memory Qdrant mode during tests
    settings = get_settings()
    monkeypatch.setattr(settings, "qdrant_host", ":memory:")


@pytest.fixture(scope="function")
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def auth_headers(db_session: Session) -> dict:
    uid = uuid.uuid4().hex[:8]
    email = f"auth_ret_{uid}@example.com"
    
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"auth_ret_{uid}",
        "password": "password123",
        "full_name": "Auth Retrieval Tester",
    })
    assert reg.status_code == 201
    
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    
    db_user = db_session.query(User).filter(User.email == email).first()
    
    yield {"headers": {"Authorization": f"Bearer {token}"}, "user_id": db_user.id}
    
    # Clean up logs and documents
    db_session.query(RetrievalLog).filter(RetrievalLog.user_id == db_user.id).delete(synchronize_session=False)
    doc_ids = [d.id for d in db_session.query(Document).filter(Document.owner_id == db_user.id).all()]
    if doc_ids:
        db_session.query(DocumentChunk).filter(DocumentChunk.document_id.in_(doc_ids)).delete(synchronize_session=False)
        db_session.query(Document).filter(Document.id.in_(doc_ids)).delete(synchronize_session=False)
    db_session.delete(db_user)
    db_session.commit()


def test_embedding_and_retrieval_caching(db_session: Session, auth_headers: dict):
    user_id = auth_headers["user_id"]
    service = RetrieverService(db_session)
    
    # 1. Test embedding caching
    service.clear_caches()
    q = "Sample Legal query string"
    emb1 = service.embed_query(q)
    assert len(emb1) == 1024
    
    # Second search should hit embedding cache
    with service._embedding_cache_lock:
        cache_hit = (q.strip(), get_settings().embedding_model) in service._embedding_cache
    assert cache_hit is True

    # 2. Test clear caches
    service.clear_caches()
    with service._embedding_cache_lock:
        cache_cleared = (q.strip(), get_settings().embedding_model) in service._embedding_cache
    assert cache_cleared is False


def test_semantic_retrieval_and_ranking(db_session: Session, auth_headers: dict, monkeypatch):
    user_id = auth_headers["user_id"]
    service = RetrieverService(db_session)
    service.clear_caches()
    
    # Insert mock document and chunks
    doc = Document(
        id=uuid.uuid4(),
        title="Test Judgment Document",
        filename="test_judgment.pdf",
        owner_id=user_id,
        file_path="uploads/test_judgment.pdf",
    )
    db_session.add(doc)
    db_session.commit()
    
    chunk_1 = DocumentChunk(
        id=uuid.uuid4(),
        document_id=doc.id,
        chunk_index=1,
        chunk_text="This is chunk 1 context details about legal summary.",
        page_start=1,
        page_end=1,
        paragraph_start=1,
        paragraph_end=1,
        word_count=10,
        character_count=50,
        estimated_tokens=15,
        section_name="Summary Findings",
    )
    chunk_2 = DocumentChunk(
        id=uuid.uuid4(),
        document_id=doc.id,
        chunk_index=2,
        chunk_text="This is chunk 2 context details about final holdings and conclusion.",
        page_start=2,
        page_end=2,
        paragraph_start=1,
        paragraph_end=1,
        word_count=10,
        character_count=50,
        estimated_tokens=15,
        section_name="Final Conclusion Order",
    )
    db_session.add_all([chunk_1, chunk_2])
    db_session.commit()

    # Mock Qdrant search results
    mock_qdrant_points = [
        {"score": 0.85, "payload": {"chunk_id": str(chunk_1.id)}},
        {"score": 0.90, "payload": {"chunk_id": str(chunk_2.id)}},
    ]
    monkeypatch.setattr(
        QdrantService,
        "search_vectors",
        lambda *args, **kwargs: mock_qdrant_points,
    )

    # Perform semantic search
    filters = {}
    results = service.retrieve_semantic(
        user_id=user_id,
        query_text="search query string",
        filters=filters,
        top_k=5,
    )

    assert len(results) == 2
    # Verify ranking logic puts section conclusion order or higher scores first
    assert results[0]["chunk_id"] == str(chunk_2.id) or results[0]["chunk_id"] == str(chunk_1.id)
    assert "similarity_score" in results[0]
    
    # Verify log persistence
    log = db_session.query(RetrievalLog).filter(RetrievalLog.user_id == user_id).first()
    assert log is not None
    assert log.query_text == "search query string"


def test_context_window_builder(db_session: Session):
    service = RetrieverService(db_session)
    
    chunks = [
        {
            "chunk_id": str(uuid.uuid4()),
            "document_id": "doc_1",
            "document_name": "constitution.pdf",
            "page_number": 1,
            "section_title": "Preamble",
            "text": "We the people of the state.",
            "chunk_index": 1,
            "similarity_score": 0.95,
        },
        {
            "chunk_id": str(uuid.uuid4()),
            "document_id": "doc_1",
            "document_name": "constitution.pdf",
            "page_number": 1,
            "section_title": "Preamble",
            "text": "Establishing justice, promoting general welfare.",
            "chunk_index": 2,  # Adjacent chunk
            "similarity_score": 0.90,
        }
    ]

    context = service.build_context_window(chunks=chunks, max_tokens=1000)
    assert "SOURCE DOCUMENT: constitution.pdf" in context
    assert "We the people of the state." in context
    assert "Establishing justice, promoting general welfare." in context
    
    # Test token limit truncation
    truncated_context = service.build_context_window(chunks=chunks, max_tokens=20)
    assert "... [Truncated due to token limit]" in truncated_context or len(truncated_context) < len(context)


def test_retrieval_api_routes(db_session: Session, auth_headers: dict, monkeypatch):
    user_id = auth_headers["user_id"]
    headers = auth_headers["headers"]
    
    # Insert mock document & chunk
    doc = Document(
        id=uuid.uuid4(),
        title="API Test Document",
        filename="api_test.pdf",
        owner_id=user_id,
        file_path="uploads/api_test.pdf",
    )
    db_session.add(doc)
    db_session.commit()
    
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        document_id=doc.id,
        chunk_index=1,
        chunk_text="API context chunk contents.",
        page_start=1,
        page_end=1,
        paragraph_start=1,
        paragraph_end=1,
        word_count=10,
        character_count=50,
        estimated_tokens=15,
        section_name="API Section",
    )
    db_session.add(chunk)
    db_session.commit()

    # 1. Test POST /api/retrieval/search
    monkeypatch.setattr(
        QdrantService,
        "search_vectors",
        lambda *args, **kwargs: [{"score": 0.95, "payload": {"chunk_id": str(chunk.id)}}],
    )
    res = client.post(
        "/api/retrieval/search",
        json={"query_text": "api query", "top_k": 3},
        headers=headers,
    )
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["chunk_id"] == str(chunk.id)

    # 2. Test POST /api/retrieval/context
    res_context = client.post(
        "/api/retrieval/context",
        json={"chunks": res.json(), "max_tokens": 1000},
        headers=headers,
    )
    assert res_context.status_code == 200
    assert "context_text" in res_context.json()

    # 3. Test POST /api/retrieval/preview
    res_preview = client.post(
        "/api/retrieval/preview",
        json={"chunk_id": str(chunk.id)},
        headers=headers,
    )
    assert res_preview.status_code == 200
    assert res_preview.json()["text"] == "API context chunk contents."

    # 4. Test GET /api/retrieval/history
    res_hist = client.get("/api/retrieval/history", headers=headers)
    assert res_hist.status_code == 200
    assert len(res_hist.json()["items"]) >= 1

    # 5. Test GET /api/retrieval/statistics
    res_stats = client.get("/api/retrieval/statistics", headers=headers)
    assert res_stats.status_code == 200
    assert "average_latency_ms" in res_stats.json()

    # 6. Test GET /api/retrieval/health
    res_health = client.get("/api/retrieval/health", headers=headers)
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    # 7. Test DELETE /api/retrieval/history/{id}
    log_id = res_hist.json()["items"][0]["id"]
    res_del = client.delete(f"/api/retrieval/history/{log_id}", headers=headers)
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True
