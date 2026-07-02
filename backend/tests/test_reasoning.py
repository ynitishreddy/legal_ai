import json
import uuid
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from main import app
from app.db.session import SessionLocal
from app.models import User, Case, TimelineEvent, LegalFact, LegalEntity
from app.models.reasoning import ResearchSession, QAHistory
from app.services.reasoning.query_understanding import QueryUnderstandingService
from app.services.reasoning.multi_hop import MultiHopRetrievalOrchestrator
from app.services.reasoning.evidence import EvidenceRankingEngine, CitationRankingEngine
from app.services.reasoning.contradiction import ContradictionDetectionEngine
from app.services.reasoning.planner import LegalReasoningPlanner, ReasoningChainBuilder
from app.services.reasoning.validation import AnswerValidationEngine
from app.services.reasoning.confidence import ConfidenceCalibrationEngine
from app.services.reasoning.engine import LegalReasoningEngine

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
    email = f"reason_test_{uid}@example.com"
    
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"reason_test_{uid}",
        "password": "password123",
        "full_name": "Reasoning Tester",
    })
    assert reg.status_code == 201
    
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    
    db_user = db_session.query(User).filter(User.email == email).first()
    
    # Create a default mock case to associate with tests
    case = Case(
        id=uuid.uuid4(),
        title="Reasoning Test Case",
        status="open",
        priority="medium",
        owner_id=db_user.id
    )
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)

    yield {
        "headers": {"Authorization": f"Bearer {token}"},
        "user_id": db_user.id,
        "case_id": case.id
    }
    
    # Cleanup
    db_session.query(TimelineEvent).filter(TimelineEvent.case_id == case.id).delete()
    db_session.query(LegalFact).filter(LegalFact.case_id == case.id).delete()
    db_session.query(LegalEntity).filter(LegalEntity.case_id == case.id).delete()
    db_session.query(ResearchSession).filter(ResearchSession.user_id == db_user.id).delete()
    db_session.query(QAHistory).filter(QAHistory.user_id == db_user.id).delete()
    db_session.delete(case)
    db_session.delete(db_user)
    db_session.commit()


def test_query_classification():
    service = QueryUnderstandingService()
    
    # Test timeline intent match
    res_timeline = service.classify_query("Show me the timeline of events for this case")
    assert res_timeline["intent"] == "Timeline Question"
    assert res_timeline["strategy"] == "Timeline reasoning"
    
    # Test comparative intent match
    res_compare = service.classify_query("Compare the witness testimonies side-by-side")
    assert res_compare["intent"] == "Comparative Analysis"
    assert res_compare["strategy"] == "Comparative reasoning"


def test_evidence_and_citation_ranking(db_session: Session, auth_headers: dict):
    case_id = auth_headers["case_id"]
    engine = EvidenceRankingEngine(db_session)
    cit_engine = CitationRankingEngine()
    
    retrieved = {
        "semantic_chunks": [
            {"chunk_id": str(uuid.uuid4()), "chunk_text": "The contract was signed on January 1st.", "score": 0.85},
            {"chunk_id": str(uuid.uuid4()), "chunk_text": "Another document detail.", "score": 0.65}
        ],
        "timeline_events": [
            {"id": str(uuid.uuid4()), "title": "Signing", "date": "2026-01-01", "description": "Signing of contract", "confidence": 0.90}
        ],
        "entities": []
    }
    
    ranked_evidence = engine.rank_evidence(case_id, "contract signature date", retrieved)
    assert len(ranked_evidence) == 3
    assert ranked_evidence[0]["score"] >= 0.80
    
    citations = [
        {"id": "cit-1", "text": "Signing of contract", "source_doc": "Doc A", "score": 0.88},
        {"id": "cit-2", "text": "Signing of contract", "source_doc": "Doc A", "score": 0.88}, # Duplicate snippet
        {"id": "cit-3", "text": "General notice details", "source_doc": "Doc B", "score": 0.55}
    ]
    ranked_citations = cit_engine.rank_citations(citations)
    # Deduplicated from 3 to 2
    assert len(ranked_citations) == 2
    assert ranked_citations[0]["strength"] == "Primary"
    assert ranked_citations[1]["strength"] == "Contextual"


def test_contradiction_detection(db_session: Session, auth_headers: dict):
    case_id = auth_headers["case_id"]
    
    # Add timeline events with conflicting dates for the same semantic title
    evt1 = TimelineEvent(
        case_id=case_id,
        title="Delivery Notice Received",
        description="First delivery notice log.",
        event_date="2026-01-15T00:00:00Z",
        confidence_score=0.90
    )
    evt2 = TimelineEvent(
        case_id=case_id,
        title="Delivery Notice Received",
        description="Conflicting second notice log.",
        event_date="2026-02-15T00:00:00Z",
        confidence_score=0.90
    )
    db_session.add(evt1)
    db_session.add(evt2)
    db_session.commit()
    
    engine = ContradictionDetectionEngine(db_session)
    report = engine.detect_contradictions(case_id)
    
    assert len(report["contradictions"]) > 0
    assert "inconsistent dates" in report["contradictions"][0]["summary"].lower()


def test_confidence_calibration():
    engine = ConfidenceCalibrationEngine()
    
    retrieved = {
        "semantic_chunks": [{"score": 0.88}, {"score": 0.72}],
        "entities": [{"name": "Plaintiff"}],
        "timeline_events": [{"title": "Event 1"}]
    }
    citations = [{"id": "c1"}, {"id": "c2"}]
    contradictions = [] # Agreement
    
    calibration = engine.calibrate_confidence(retrieved, citations, contradictions)
    assert calibration["overall_confidence"] >= 0.70
    assert "retrieval_quality" in calibration["breakdown"]


def test_answer_validation():
    engine = AnswerValidationEngine()
    
    retrieved = {
        "semantic_chunks": [{"chunk_text": "Section 45 Arbitration clause was breached."}],
    }
    
    warnings = engine.validate_answer(
        question="Was arbitration clause breached?",
        answer="The court verified Section 99 Arbitration was breached.",
        retrieved_data=retrieved,
        citations=[],
        confidence_threshold=0.90
    )
    
    assert warnings["success"] is False
    assert len(warnings["warnings"]) > 0
    # references section not in context
    assert any("Section 99" in w["warning"] for w in warnings["warnings"])


def test_api_reasoning_endpoints(auth_headers: dict):
    headers = auth_headers["headers"]
    case_id = str(auth_headers["case_id"])
    
    # Test Classify Endpoint
    res_classify = client.post(f"/api/reasoning/classify?query_text=Compare witness timelines", headers=headers)
    assert res_classify.status_code == 200
    assert res_classify.json()["intent"] == "Comparative Analysis"
    
    # Test Compare Endpoint
    res_compare = client.post("/api/reasoning/compare", json={
        "case_id": case_id,
        "target_type": "case",
        "item_ids": [case_id, case_id]
    }, headers=headers)
    assert res_compare.status_code == 200
    assert "similarity_score" in res_compare.json()

    # Test QA Endpoint
    res_qa = client.post("/api/reasoning/qa", json={
        "question": "What is the status of the Arbitration contract covenants?",
        "case_id": case_id,
        "provider": "mock",
        "stream": False
    }, headers=headers)
    assert res_qa.status_code == 200
    assert "answer" in res_qa.json()
    assert "confidence" in res_qa.json()
    
    # Test Research Session Endpoint
    res_session = client.post("/api/reasoning/research/sessions", json={
        "title": "Arbitration breach analysis",
        "case_id": case_id
    }, headers=headers)
    assert res_session.status_code == 201
    session_id = res_session.json()["id"]
    
    # Add note
    res_note = client.post(f"/api/reasoning/research/sessions/{session_id}/notes", json={
        "title": "Witness A notes",
        "content": "Witness statements do not align with exhibit delivery receipt dates."
    }, headers=headers)
    assert res_note.status_code == 201
    
    # Get sessions list
    res_list = client.get(f"/api/reasoning/research/sessions?case_id={case_id}", headers=headers)
    assert res_list.status_code == 200
    assert len(res_list.json()) == 1
    assert res_list.json()[0]["title"] == "Arbitration breach analysis"
    assert len(res_list.json()[0]["notes"]) == 1
