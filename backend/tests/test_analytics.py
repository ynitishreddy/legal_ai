import uuid
import json
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from main import app
from app.db.session import SessionLocal
from app.models import (
    Case, Document, ProcessingJob, ChatSession, ChatMessage,
    AnalyticsRecord, AnalyticsSnapshot, User
)
from app.services.analytics import AnalyticsService

client = TestClient(app)


@pytest.fixture(scope="function")
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def test_user_and_case(db):
    """Seeds a test user and case to run real metrics aggregation tests."""
    u = User(
        email=f"analytics_test_{uuid.uuid4().hex[:6]}@example.com",
        username=f"analytics_test_{uuid.uuid4().hex[:6]}",
        hashed_password="pw"
    )
    db.add(u)
    db.flush()

    c = Case(
        title="Analytics Test Case",
        court_name="Supreme Court of India",
        jurisdiction="New Delhi",
        status="open",
        priority="high",
        owner_id=u.id
    )
    db.add(c)
    db.commit()

    yield {"user_id": u.id, "case_id": c.id}

    # Cleanup
    db.query(AnalyticsSnapshot).filter(AnalyticsSnapshot.case_id == c.id).delete()
    db.query(Case).filter(Case.id == c.id).delete()
    db.query(User).filter(User.id == u.id).delete()
    db.commit()


# ─────────────────────────────────────────────
# Unit / Integration Tests
# ─────────────────────────────────────────────

def test_analytics_service_computes_overview(db, test_user_and_case):
    case_id = test_user_and_case["case_id"]
    service = AnalyticsService(db)
    
    # Verify we can load overview metrics and charts
    overview = service.get_overview(case_id=case_id)
    assert "metrics" in overview
    assert "charts" in overview
    assert "summary" in overview
    assert overview["summary"]["total_cases"] >= 1


def test_analytics_service_cache_and_snapshots(db, test_user_and_case):
    case_id = test_user_and_case["case_id"]
    service = AnalyticsService(db)

    # 1. Clear existing cache snapshot for category 'cases'
    db.query(AnalyticsSnapshot).filter(
        AnalyticsSnapshot.snapshot_type == "cases",
        AnalyticsSnapshot.case_id == case_id
    ).delete()
    db.commit()

    # 2. Retrieve (should execute live calculation and write to DB)
    data_first = service.get_cached_or_compute("cases", case_id)
    assert len(data_first["metrics"]) > 0

    # Verify snapshot row was added to cache
    snapshot = db.query(AnalyticsSnapshot).filter(
        AnalyticsSnapshot.snapshot_type == "cases",
        AnalyticsSnapshot.case_id == case_id
    ).first()
    assert snapshot is not None
    assert json.loads(snapshot.data_json)["metrics"][0]["name"] == "Total Cases"

    # 3. Retrieve second time (should pull directly from DB cache)
    data_second = service.get_cached_or_compute("cases", case_id)
    assert data_first["metrics"][0]["value"] == data_second["metrics"][0]["value"]


def test_analytics_api_endpoints(db, test_user_and_case):
    case_id = test_user_and_case["case_id"]

    # Test overview fetch
    resp = client.get(f"/api/analytics?case_id={case_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "metrics" in data
    assert "summary" in data

    # Test category endpoint
    resp = client.get(f"/api/analytics/cases?case_id={case_id}")
    assert resp.status_code == 200
    cat_data = resp.json()
    assert "cases_by_status" in cat_data

    # Test refresh manual route
    resp = client.post(f"/api/analytics/refresh?case_id={case_id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Test export CSV download stream
    resp = client.get(f"/api/analytics/export?category=cases&case_id={case_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment; filename=" in resp.headers["content-disposition"]
