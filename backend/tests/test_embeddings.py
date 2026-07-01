import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from main import app
from app.db.session import SessionLocal
from app.models import (
    Case,
    Document,
    JobStatus,
    ProcessingJob,
    User,
    UserRole,
    JobType,
)
from app.document_processing.models import DocumentChunk
from app.models.embeddings import DocumentEmbedding, EmbeddingJob
from app.services.embeddings import EmbeddingService, DocumentEmbeddingService

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_sentence_transformers(monkeypatch):
    import sentence_transformers
    def mock_init(*args, **kwargs):
        raise RuntimeError("HF Network offline / Simulated offline mode for testing")
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", mock_init)


@pytest.fixture(scope="function")
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_user(db_session: Session) -> User:
    uid = uuid.uuid4().hex[:6]
    user = User(
        email=f"emb_test_{uid}@example.com",
        username=f"emb_test_{uid}",
        hashed_password="hashed_password_placeholder",
        full_name="Embedding Tester",
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    yield user
    # Cleanup
    doc_ids = [d.id for d in db_session.query(Document).filter(Document.owner_id == user.id).all()]
    if doc_ids:
        db_session.query(DocumentEmbedding).filter(DocumentEmbedding.document_id.in_(doc_ids)).delete(synchronize_session=False)
        db_session.query(EmbeddingJob).filter(EmbeddingJob.document_id.in_(doc_ids)).delete(synchronize_session=False)
    db_session.query(ProcessingJob).filter(ProcessingJob.user_id == user.id).delete(synchronize_session=False)
    if doc_ids:
        db_session.query(DocumentChunk).filter(DocumentChunk.document_id.in_(doc_ids)).delete(synchronize_session=False)
        db_session.query(Document).filter(Document.id.in_(doc_ids)).delete(synchronize_session=False)
    db_session.query(Case).filter(Case.owner_id == user.id).delete(synchronize_session=False)
    db_session.delete(user)
    db_session.commit()


@pytest.fixture
def auth_headers(db_session: Session) -> dict:
    uid = uuid.uuid4().hex[:8]
    email = f"auth_test_{uid}@example.com"
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"auth_test_{uid}",
        "password": "password123",
        "full_name": "Auth Tester",
    })
    assert reg.status_code == 201
    
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    
    db_user = db_session.query(User).filter(User.email == email).first()
    
    yield {"headers": {"Authorization": f"Bearer {token}"}, "user_id": db_user.id}
    
    # Cleanup auth user
    doc_ids = [d.id for d in db_session.query(Document).filter(Document.owner_id == db_user.id).all()]
    if doc_ids:
        db_session.query(DocumentEmbedding).filter(DocumentEmbedding.document_id.in_(doc_ids)).delete(synchronize_session=False)
        db_session.query(EmbeddingJob).filter(EmbeddingJob.document_id.in_(doc_ids)).delete(synchronize_session=False)
    db_session.query(ProcessingJob).filter(ProcessingJob.user_id == db_user.id).delete(synchronize_session=False)
    if doc_ids:
        db_session.query(DocumentChunk).filter(DocumentChunk.document_id.in_(doc_ids)).delete(synchronize_session=False)
        db_session.query(Document).filter(Document.id.in_(doc_ids)).delete(synchronize_session=False)
    db_session.query(Case).filter(Case.owner_id == db_user.id).delete(synchronize_session=False)
    db_session.delete(db_user)
    db_session.commit()



@pytest.fixture
def test_document(db_session: Session, test_user: User) -> Document:
    case = Case(title="Test Case", owner_id=test_user.id)
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)

    doc = Document(
        title="Test Doc",
        filename="test.txt",
        file_path="uploads/test.txt",
        owner_id=test_user.id,
        case_id=case.id,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    yield doc


@pytest.fixture
def test_chunks(db_session: Session, test_document: Document) -> list[DocumentChunk]:
    chunks = []
    for i in range(3):
        chunk = DocumentChunk(
            document_id=test_document.id,
            chunk_index=i,
            section_name="General",
            chunk_text=f"This is test chunk number {i} text contents.",
            page_start=1,
            page_end=1,
            paragraph_start=i,
            paragraph_end=i,
            word_count=8,
            character_count=45,
            estimated_tokens=10,
        )
        db_session.add(chunk)
        chunks.append(chunk)
    db_session.commit()
    for c in chunks:
        db_session.refresh(c)
    return chunks


# ── 1. Test Inference Service ──────────────────────────────────────────────────

def test_embedding_service_singleton():
    svc1 = EmbeddingService()
    svc2 = EmbeddingService()
    assert svc1 is svc2


def test_embedding_service_model_info():
    svc = EmbeddingService()
    info = svc.get_model_info()
    assert "model_name" in info
    assert "dimension" in info
    assert "version" in info
    assert "loaded" in info


def test_embedding_service_inference():
    svc = EmbeddingService()
    text = "Verify this single text generation."
    vector = svc.embed_text(text)
    assert isinstance(vector, list)
    assert len(vector) == svc.dimension
    assert all(isinstance(val, float) for val in vector)


def test_embedding_service_batch_inference():
    svc = EmbeddingService()
    texts = ["Sentence one.", "Sentence two.", "Sentence three."]
    vectors = svc.embed_batch(texts)
    assert len(vectors) == 3
    for vec in vectors:
        assert len(vec) == svc.dimension


# ── 2. Test Db Service & Worker logic ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_sync_embedding_job(db_session: Session, test_user: User, test_document: Document, test_chunks: list[DocumentChunk]):
    service = DocumentEmbeddingService(db_session)
    job = await service.create_embedding_job(
        user_id=test_user.id,
        document_id=test_document.id,
    )
    assert job.document_id == test_document.id
    assert job.status == JobStatus.PENDING

    # Verify corresponding ProcessingJob was created
    proc_job = db_session.get(ProcessingJob, job.id)
    assert proc_job is not None
    assert proc_job.job_type == JobType.EMBEDDINGS
    assert proc_job.status == JobStatus.QUEUED


@pytest.mark.asyncio
async def test_embedding_status(db_session: Session, test_user: User, test_document: Document, test_chunks: list[DocumentChunk]):
    service = DocumentEmbeddingService(db_session)
    status_data = service.get_embedding_status(document_id=test_document.id, user_id=test_user.id)
    assert status_data["status"] == "never_embedded"
    assert status_data["total_chunks"] == 3
    assert status_data["embedded_chunks"] == 0


# ── 3. Test REST APIs ──────────────────────────────────────────────────────────

def test_api_embed_document(auth_headers: dict, db_session: Session):
    headers = auth_headers["headers"]
    user_id = auth_headers["user_id"]
    
    # Create doc
    doc = Document(
        title="API Doc",
        filename="test.txt",
        file_path="uploads/test.txt",
        owner_id=user_id,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    
    # Add chunks
    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        chunk_text="This is text to embed via REST API.",
        page_start=1, page_end=1, paragraph_start=0, paragraph_end=0,
        word_count=5, character_count=30, estimated_tokens=8,
    )
    db_session.add(chunk)
    db_session.commit()

    # Trigger embed via API
    response = client.post(f"/api/documents/{doc.id}/embed", headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["document_id"] == str(doc.id)
    assert data["status"] == "pending"


def test_api_get_embedding_statistics(auth_headers: dict):
    headers = auth_headers["headers"]
    response = client.get("/api/embeddings/statistics", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "total_embedded_documents" in data
    assert "total_embedded_chunks" in data
    assert "embedding_queue_size" in data
