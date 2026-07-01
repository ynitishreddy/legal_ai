import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from main import app
from app.db.session import SessionLocal
from app.core.config import get_settings
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
from app.models.embeddings import DocumentEmbedding, VectorSyncJob
from app.services.qdrant import QdrantService
from app.services.vector_sync import VectorSyncService

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
def test_user(db_session: Session) -> User:
    uid = uuid.uuid4().hex[:6]
    user = User(
        email=f"vec_test_{uid}@example.com",
        username=f"vec_test_{uid}",
        hashed_password="hashed_password_placeholder",
        full_name="Vector Tester",
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
        db_session.query(VectorSyncJob).filter(VectorSyncJob.document_id.in_(doc_ids)).delete(synchronize_session=False)
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
    email = f"auth_vec_{uid}@example.com"
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"auth_vec_{uid}",
        "password": "password123",
        "full_name": "Auth Vector Tester",
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
        db_session.query(VectorSyncJob).filter(VectorSyncJob.document_id.in_(doc_ids)).delete(synchronize_session=False)
    db_session.query(ProcessingJob).filter(ProcessingJob.user_id == db_user.id).delete(synchronize_session=False)
    if doc_ids:
        db_session.query(DocumentChunk).filter(DocumentChunk.document_id.in_(doc_ids)).delete(synchronize_session=False)
        db_session.query(Document).filter(Document.id.in_(doc_ids)).delete(synchronize_session=False)
    db_session.query(Case).filter(Case.owner_id == db_user.id).delete(synchronize_session=False)
    db_session.delete(db_user)
    db_session.commit()


@pytest.fixture
def test_document(db_session: Session, test_user: User) -> Document:
    case = Case(title="Vector Case", owner_id=test_user.id)
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)

    doc = Document(
        title="Vector Doc",
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
def test_embeddings_and_chunks(db_session: Session, test_document: Document) -> list[DocumentEmbedding]:
    embeddings = []
    for i in range(3):
        chunk = DocumentChunk(
            document_id=test_document.id,
            chunk_index=i,
            section_name="General",
            chunk_text=f"Chunk payload content value {i}.",
            page_start=1, page_end=1, paragraph_start=i, paragraph_end=i,
            word_count=5, character_count=30, estimated_tokens=10,
        )
        db_session.add(chunk)
        db_session.commit()
        db_session.refresh(chunk)

        emb = DocumentEmbedding(
            document_id=test_document.id,
            chunk_id=chunk.id,
            embedding_vector=[0.1 * i] * 1024,
            embedding_dimension=1024,
            embedding_model="BAAI/bge-large-en-v1.5",
            embedding_version="1.5",
        )
        db_session.add(emb)
        embeddings.append(emb)
    
    db_session.commit()
    for e in embeddings:
        db_session.refresh(e)
    return embeddings


# ── 1. Qdrant Service Tests ──────────────────────────────────────────────────

def test_qdrant_service_singleton():
    svc1 = QdrantService()
    svc2 = QdrantService()
    assert svc1 is svc2


def test_qdrant_service_health():
    svc = QdrantService()
    health = svc.health_check()
    assert health["status"] == "healthy"
    assert health["mode"] == "memory"
    assert "vector_count" in health


def test_qdrant_service_collection_info():
    svc = QdrantService()
    info = svc.get_collection_info()
    assert info["name"] == svc.collection_name
    assert info["dimension"] == 1024


# ── 2. Vector Sync Service Tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_sync_job(db_session: Session, test_user: User, test_document: Document):
    service = VectorSyncService(db_session)
    job = await service.create_sync_job(
        user_id=test_user.id,
        document_id=test_document.id,
    )
    assert job.document_id == test_document.id
    assert job.status == JobStatus.PENDING

    # Check ProcessingJob creation
    proc_job = db_session.get(ProcessingJob, job.id)
    assert proc_job is not None
    assert proc_job.job_type == JobType.VECTOR_SYNC
    assert proc_job.status == JobStatus.QUEUED


@pytest.mark.asyncio
async def test_sync_document_vectors(db_session: Session, test_user: User, test_document: Document, test_embeddings_and_chunks: list[DocumentEmbedding]):
    service = VectorSyncService(db_session)
    
    # Run sync
    success = await service.sync_document_vectors(
        job_id=uuid.uuid4(),
        document_id=test_document.id,
    )
    assert success is True

    # Check that database records are updated
    db_embeddings = db_session.query(DocumentEmbedding).filter(DocumentEmbedding.document_id == test_document.id).all()
    for emb in db_embeddings:
        assert emb.is_synced is True
        assert emb.synced_at is not None


# ── 3. REST API Router Tests ─────────────────────────────────────────────────

def test_api_qdrant_health(auth_headers: dict):
    headers = auth_headers["headers"]
    response = client.get("/api/vectors/health", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["mode"] == "memory"


def test_api_get_statistics(auth_headers: dict):
    headers = auth_headers["headers"]
    response = client.get("/api/vectors/statistics", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "total_vectors" in data
    assert "synced_vectors" in data


def test_api_get_collections(auth_headers: dict):
    headers = auth_headers["headers"]
    response = client.get("/api/vectors/collections", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["vectors_count"] is not None


def test_api_sync_document(auth_headers: dict, db_session: Session):
    headers = auth_headers["headers"]
    user_id = auth_headers["user_id"]

    # Setup doc
    doc = Document(
        title="API Sync Doc",
        filename="test.txt",
        file_path="uploads/test.txt",
        owner_id=user_id,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    response = client.post(f"/api/vectors/sync/document/{doc.id}", headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["document_id"] == str(doc.id)
    assert data["status"] == "pending"
