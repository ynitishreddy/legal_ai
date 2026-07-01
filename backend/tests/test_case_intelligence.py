import uuid
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from main import app
from app.db.session import SessionLocal
from app.models import (
    LegalFact,
    LegalEntity,
    LegalIssue,
    ClaimDefense,
    LegalEvidence,
    ActStatute,
    EntityRelationship,
    Case,
    Document,
    User
)
from app.document_processing.models import DocumentChunk
from app.services.case_intelligence.extractors import (
    PartyExtractor,
    JudgeExtractor,
    CourtExtractor,
    StatuteExtractor
)
from app.services.case_intelligence.service import CaseIntelligenceService

client = TestClient(app)


@pytest.fixture(scope="function")
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_extractors_regex_patterns():
    # 1. PartyExtractor
    party_ext = PartyExtractor()
    text = "The plaintiff John Smith filed a suit against the defendant Amit Patel."
    res = party_ext.extract(text, {})
    assert len(res) >= 2
    names = [r["name"] for r in res]
    assert "John Smith" in names
    assert "Amit Patel" in names

    # 2. JudgeExtractor
    judge_ext = JudgeExtractor()
    text = "Coram: Justice R. F. Nariman and Hon'ble Judge Malhotra presiding."
    res = judge_ext.extract(text, {})
    names = [r["name"] for r in res]
    print(f"DEBUG JUDGE NAMES: {names}")
    assert "R. F. Nariman" in names or any("Nariman" in n for n in names)
    assert "Malhotra" in names or any("Malhotra" in n for n in names)

    # 3. CourtExtractor
    court_ext = CourtExtractor()
    text = "Before the Delhi High Court at New Delhi."
    res = court_ext.extract(text, {})
    assert len(res) == 1
    assert res[0]["name"] == "Delhi High Court"

    # 4. StatuteExtractor
    stat_ext = StatuteExtractor()
    text = "He was charged under Section 302 of the Indian Penal Code."
    res = stat_ext.extract(text, {})
    assert len(res) == 1
    assert res[0]["act_name"] == "Indian Penal Code"
    assert res[0]["section_reference"] == "Section 302"


def test_case_intelligence_service_flow(db_session: Session):
    # Setup user, case, and doc mimicking test_timeline.py working mock setup
    u_id = uuid.uuid4()
    c_id = uuid.uuid4()
    d_id = uuid.uuid4()

    user = User(
        id=u_id,
        email=f"user_{u_id.hex[:6]}@example.com",
        username=f"user_{u_id.hex[:6]}",
        hashed_password="pw"
    )
    mock_case = Case(
        id=c_id,
        title="Timeline Case",
        owner_id=u_id
    )
    mock_doc = Document(
        id=d_id,
        title="Agreement.pdf",
        filename="Agreement.pdf",
        file_path="mock_agreement.pdf",
        case_id=c_id,
        owner_id=u_id
    )
    db_session.add_all([user, mock_case, mock_doc])
    db_session.commit()

    # Create chunks containing matches
    chunk = DocumentChunk(
        document_id=d_id,
        chunk_index=0,
        chunk_text=(
            "The plaintiff John Smith signed the contract on Jan 1. "
            "Before Justice Amit Malhotra at Delhi High Court. "
            "Charged under Section 302 of the Indian Penal Code. "
            "Witness PW-1 Ramesh Kumar testified that the incident occurred. "
            "The petitioner John Smith prays for compensation of Rs 5 Lakhs."
        ),
        page_start=1,
        page_end=1,
        paragraph_start=1,
        paragraph_end=1,
        word_count=50,
        character_count=300,
        estimated_tokens=70
    )
    db_session.add(chunk)
    db_session.commit()

    service = CaseIntelligenceService(db_session)
    counts = service.extract_case_knowledge(c_id, d_id)

    assert counts["facts"] > 0
    assert counts["entities"] > 0
    assert counts["statutes"] > 0

    # Verify entity resolution merged John Smith and grouped aliases
    resolved = db_session.query(LegalEntity).filter(
        LegalEntity.case_id == c_id,
        LegalEntity.normalized_name == "JOHN SMITH"
    ).first()
    assert resolved is not None

    # Verify Knowledge Graph structure compiles node-link data
    graph = service.get_knowledge_graph_data(c_id)
    assert len(graph["nodes"]) > 0
    assert len(graph["links"]) > 0

    # Cleanup
    db_session.delete(chunk)
    db_session.delete(mock_doc)
    db_session.delete(mock_case)
    db_session.commit()


def test_intelligence_api_endpoints(db_session: Session):
    # Setup user
    uid = uuid.uuid4().hex[:8]
    user = User(email=f"testowner_{uid}@example.com", username=f"testowner_{uid}", hashed_password="pwd", role="admin")
    db_session.add(user)
    db_session.commit()

    # Setup mock Case
    mock_case = Case(
        title="Test API Case",
        status="open",
        priority="medium",
        owner_id=user.id
    )
    db_session.add(mock_case)
    db_session.commit()

    # Add mock fact
    mock_fact = LegalFact(
        case_id=mock_case.id,
        fact_text="Mock fact details",
        confidence_score=0.90,
        extraction_method="llm"
    )
    db_session.add(mock_fact)
    db_session.commit()

    # Get facts
    response = client.get(f"/api/intelligence/facts?case_id={mock_case.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["fact_text"] == "Mock fact details"

    # Get graph data
    response = client.get(f"/api/intelligence/case/{mock_case.id}")
    assert response.status_code == 200
    graph = response.json()
    assert "nodes" in graph
    assert "links" in graph

    # Cleanup
    db_session.delete(mock_fact)
    db_session.delete(mock_case)
    db_session.commit()
