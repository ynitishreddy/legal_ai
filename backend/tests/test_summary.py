import uuid
import json
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from main import app
from app.db.session import SessionLocal
from app.models import Case, User, TimelineEvent, LegalFact, JobStatus
from app.models.summary import Summary, SummaryVersion, SummaryCitation, SummaryCache, SummaryGenerationJob
from app.services.summary import SummaryService, SummaryCacheManager

client = TestClient(app)


@pytest.fixture(scope="function")
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def test_case_and_indices(db):
    """Seeds a test user, case, fact, and timeline event for resolution testing."""
    u = User(
        email=f"summary_test_{uuid.uuid4().hex[:6]}@example.com",
        username=f"summary_test_{uuid.uuid4().hex[:6]}",
        hashed_password="pw"
    )
    db.add(u)
    db.flush()

    c = Case(
        title="Summaries Test Case",
        court_name="Delhi High Court",
        jurisdiction="New Delhi",
        status="open",
        priority="high",
        owner_id=u.id
    )
    db.add(c)
    db.flush()

    f = LegalFact(
        case_id=c.id,
        fact_text="Petitioner filed contract claims on January 10th",
        confidence_score=0.95,
        extraction_method="ai"
    )
    db.add(f)

    evt = TimelineEvent(
        case_id=c.id,
        title="Contract Dispute Origin",
        description="Breach event occurred",
        event_date=datetime(2026, 1, 10)
    )
    db.add(evt)
    db.commit()

    yield {"case_id": c.id, "fact_id": f.id, "event_id": evt.id}

    # Cleanup
    db.query(SummaryCache).filter(SummaryCache.case_id == c.id).delete()
    db.query(SummaryCitation).filter(
        SummaryCitation.summary_version_id.in_(
            db.query(SummaryVersion.id).filter(
                SummaryVersion.summary_id.in_(
                    db.query(Summary.id).filter(Summary.case_id == c.id)
                )
            )
        )
    ).delete()
    db.query(SummaryVersion).filter(
        SummaryVersion.summary_id.in_(
            db.query(Summary.id).filter(Summary.case_id == c.id)
        )
    ).delete()
    db.query(Summary).filter(Summary.case_id == c.id).delete()
    db.query(SummaryGenerationJob).filter(SummaryGenerationJob.case_id == c.id).delete()
    db.query(LegalFact).filter(LegalFact.id == f.id).delete()
    db.query(TimelineEvent).filter(TimelineEvent.id == evt.id).delete()
    db.query(Case).filter(Case.id == c.id).delete()
    db.query(User).filter(User.id == u.id).delete()
    db.commit()


# To support datetime import easily inside fixture
from datetime import datetime


# ─────────────────────────────────────────────
# Unit & Integration Tests
# ─────────────────────────────────────────────

def test_summary_service_resolves_citations(db, test_case_and_indices):
    case_id = test_case_and_indices["case_id"]
    fact_id = test_case_and_indices["fact_id"]
    event_id = test_case_and_indices["event_id"]

    service = SummaryService(db)
    
    # Check citation extraction
    sample_text = f"This case involves contract issues [Fact: {fact_id}] and breach event [TimelineEvent: {event_id}]."
    citations = service._parse_citations(sample_text)

    assert len(citations) == 2
    assert citations[0]["type"] == "fact"
    assert citations[0]["id"] == fact_id
    assert citations[0]["title"] == "Legal Fact"
    assert "Petitioner filed contract claims" in citations[0]["text"]

    assert citations[1]["type"] == "timelineevent"
    assert citations[1]["id"] == event_id
    assert citations[1]["title"] == "Contract Dispute Origin"


def test_summary_generation_and_caching(db, test_case_and_indices):
    case_id = test_case_and_indices["case_id"]
    service = SummaryService(db)

    # 1. Generate new summary (cache miss)
    version_1 = service.generate_summary(
        case_id=case_id,
        summary_type="executive",
        provider="mock",
        model="mock-model",
        regenerate=True
    )
    assert version_1.version == 1
    assert version_1.is_active is True

    # 2. Get cached version (cache hit)
    version_2 = service.generate_summary(
        case_id=case_id,
        summary_type="executive",
        provider="mock",
        model="mock-model",
        regenerate=False
    )
    assert version_2.id == version_1.id
    assert version_2.version == 1

    # 3. Regenerate (force recreate version 2)
    version_3 = service.generate_summary(
        case_id=case_id,
        summary_type="executive",
        provider="mock",
        model="mock-model",
        regenerate=True
    )
    assert version_3.version == 2
    assert version_3.is_active is True
    
    # Check that version 1 is no longer active
    db.refresh(version_1)
    assert version_1.is_active is False


def test_summary_endpoints(db, test_case_and_indices):
    case_id = test_case_and_indices["case_id"]

    # Generate via POST endpoint
    resp = client.post("/api/summary/generate", json={
        "case_id": str(case_id),
        "summary_type": "executive",
        "provider": "mock",
        "model": "mock-model",
        "regenerate": True
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == 1
    version_1_id = data["id"]

    # Generate second version to support compare test
    resp2 = client.post("/api/summary/generate", json={
        "case_id": str(case_id),
        "summary_type": "executive",
        "provider": "mock",
        "model": "mock-model",
        "regenerate": True
    })
    assert resp2.status_code == 200
    version_2_id = resp2.json()["id"]

    # Test compare endpoint
    compare_resp = client.post("/api/summary/compare", json={
        "version_id_1": version_1_id,
        "version_id_2": version_2_id
    })
    assert compare_resp.status_code == 200
    assert "diff_text" in compare_resp.json()

    # Test history endpoint
    history_resp = client.get(f"/api/summary/history?case_id={case_id}&summary_type=executive")
    assert history_resp.status_code == 200
    assert len(history_resp.json()) == 2

    # Test export markdown endpoint
    export_resp = client.get(f"/api/summary/export?version_id={version_2_id}&format=markdown")
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"] == "text/markdown; charset=utf-8"
