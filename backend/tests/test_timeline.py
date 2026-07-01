import uuid
import datetime
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from main import app
from app.db.session import SessionLocal
from app.models import User, Case, Document, TimelineEvent, EventRelationship
from app.document_processing.models import DocumentChunk
from app.services.timeline import TimelineIntelligenceService

client = TestClient(app)


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
    email = f"auth_time_{uid}@example.com"
    
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"auth_time_{uid}",
        "password": "password123",
        "full_name": "Auth Timeline Tester",
    })
    assert reg.status_code == 201
    
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    
    db_user = db_session.query(User).filter(User.email == email).first()
    
    yield {"headers": {"Authorization": f"Bearer {token}"}, "user_id": db_user.id}
    
    # Cleanup logs
    db_session.query(EventRelationship).delete()
    db_session.query(TimelineEvent).delete()
    db_session.query(Document).filter(Document.owner_id == db_user.id).delete()
    db_session.query(Case).filter(Case.owner_id == db_user.id).delete()
    db_session.delete(db_user)
    db_session.commit()


def test_date_normalizations(db_session: Session):
    svc = TimelineIntelligenceService(db_session)
    
    d1 = svc.normalize_event_date("15/10/2023")
    assert d1 == datetime.datetime(2023, 10, 15, tzinfo=datetime.timezone.utc)

    d2 = svc.normalize_event_date("2023-11-20")
    assert d2 == datetime.datetime(2023, 11, 20, tzinfo=datetime.timezone.utc)

    d3 = svc.normalize_event_date("October 25, 2023")
    assert d3 == datetime.datetime(2023, 10, 25, tzinfo=datetime.timezone.utc)


def test_event_extraction_service(db_session: Session):
    # Setup Case, Doc, and Chunks
    u_id = uuid.uuid4()
    c_id = uuid.uuid4()
    d_id = uuid.uuid4()
    
    user = User(id=u_id, email=f"user_{u_id.hex[:6]}@example.com", username=f"user_{u_id.hex[:6]}", hashed_password="pw")
    case = Case(id=c_id, title="Timeline Case", owner_id=u_id)
    doc = Document(id=d_id, title="Agreement.pdf", filename="Agreement.pdf", file_path="mock_agreement.pdf", case_id=c_id, owner_id=u_id)
    
    db_session.add_all([user, case, doc])
    db_session.commit()

    chunk1 = DocumentChunk(
        document_id=d_id,
        chunk_index=0,
        chunk_text="A lease agreement was signed on 15/10/2023 by the parties.",
        page_start=1,
        page_end=1,
        paragraph_start=1,
        paragraph_end=1,
        word_count=10,
        character_count=50,
        estimated_tokens=20,
    )
    chunk2 = DocumentChunk(
        document_id=d_id,
        chunk_index=1,
        chunk_text="The Delhi High Court scheduled a hearing on 20-11-2023 for the stay petition.",
        page_start=2,
        page_end=2,
        paragraph_start=1,
        paragraph_end=1,
        word_count=10,
        character_count=50,
        estimated_tokens=20,
    )
    db_session.add_all([chunk1, chunk2])
    db_session.commit()

    svc = TimelineIntelligenceService(db_session)
    events = svc.extract_document_events(c_id, d_id)
    
    assert len(events) >= 2
    
    # Assert type mapping
    types = [e.event_type for e in events]
    assert "civil" in types # lease agreement
    assert "court" in types # Delhi High Court hearing

    # Cleanup
    db_session.query(DocumentChunk).filter(DocumentChunk.document_id == d_id).delete()
    db_session.delete(doc)
    db_session.delete(case)
    db_session.delete(user)
    db_session.commit()


def test_timeline_rest_apis(db_session: Session, auth_headers: dict):
    headers = auth_headers["headers"]
    u_id = auth_headers["user_id"]
    c_id = uuid.uuid4()
    d_id = uuid.uuid4()

    case = Case(id=c_id, title="API Case", owner_id=u_id)
    doc = Document(id=d_id, title="Suit.pdf", filename="Suit.pdf", file_path="mock_suit.pdf", case_id=c_id, owner_id=u_id)
    db_session.add_all([case, doc])
    db_session.commit()

    chunk = DocumentChunk(
        document_id=d_id,
        chunk_index=0,
        chunk_text="The contract breach occurred on 15/09/2023.",
        page_start=1,
        page_end=1,
        paragraph_start=1,
        paragraph_end=1,
        word_count=10,
        character_count=50,
        estimated_tokens=20,
    )
    db_session.add(chunk)
    db_session.commit()

    # 1. Test extract POST route
    res_ext = client.post(
        "/api/timeline/extract",
        json={"case_id": str(c_id), "document_id": str(d_id)},
        headers=headers,
    )
    assert res_ext.status_code == 201
    
    # 2. Test timeline GET list
    res_list = client.get(f"/api/timeline/case/{c_id}", headers=headers)
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1
    event_id = res_list.json()[0]["id"]

    # 3. Test stats GET route
    res_stats = client.get(f"/api/timeline/statistics?case_id={c_id}", headers=headers)
    assert res_stats.status_code == 200
    assert res_stats.json()["total_events"] >= 1

    # 4. Test search GET route
    res_sr = client.get(f"/api/timeline/search?case_id={c_id}&query=breach", headers=headers)
    assert res_sr.status_code == 200
    assert len(res_sr.json()) >= 1

    # 5. Test rebuild POST route
    res_rb = client.post(
        "/api/timeline/rebuild",
        json={"case_id": str(c_id)},
        headers=headers,
    )
    assert res_rb.status_code == 200

    # Cleanup chunk
    db_session.query(DocumentChunk).filter(DocumentChunk.document_id == d_id).delete()
    db_session.commit()
