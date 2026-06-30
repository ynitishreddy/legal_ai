"""
Integration tests for Processing API endpoints.

Tests cover: create, list, detail, cancel, retry, permissions, and duplicate prevention.
Uses FastAPI TestClient with a real test database.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(suffix: str = "") -> dict:
    """Register a new user and return auth headers."""
    uid = uuid.uuid4().hex[:8]
    tag = f"{suffix}{uid}"
    email = f"proc{tag}@example.com"
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"proc{tag}",
        "password": "password123",
        "full_name": "Processing Tester",
    })
    assert reg.status_code == 201, reg.text
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_case(headers: dict, title: str = "Test Case") -> dict:
    payload = {"title": title, "priority": "medium", "status": "open"}
    r = client.post("/api/cases", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _upload_document(headers: dict, case_id: str | None = None) -> str:
    """Upload a dummy text file and return its document id."""
    if not case_id:
        case = _create_case(headers)
        case_id = case["id"]
    content = b"Test document content for processing tests."
    files = {"file": ("test.txt", io.BytesIO(content), "text/plain")}
    data = {"title": "Processing Test Doc", "case_id": case_id}
    resp = client.post("/api/documents/upload", files=files, data=data, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

def test_create_job_requires_auth():
    resp = client.post("/api/processing/jobs", json={"document_id": str(uuid.uuid4()), "job_type": "ocr"})
    assert resp.status_code == 401


def test_list_jobs_requires_auth():
    resp = client.get("/api/processing/jobs")
    assert resp.status_code == 401


def test_active_jobs_requires_auth():
    resp = client.get("/api/processing/jobs/active")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Job creation
# ---------------------------------------------------------------------------

def test_create_job_success():
    headers = _register_and_login("create")
    doc_id = _upload_document(headers)

    resp = client.post("/api/processing/jobs", json={
        "document_id": doc_id,
        "job_type": "text_extraction",
        "priority": "normal",
        "max_retries": 2,
    }, headers=headers)

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["document_id"] == doc_id
    assert data["job_type"] == "text_extraction"
    assert data["status"] in {"pending", "queued"}
    assert data["progress_percentage"] == 0
    assert data["retry_count"] == 0
    assert data["max_retries"] == 2


def test_create_job_invalid_type():
    headers = _register_and_login("badtype")
    doc_id = _upload_document(headers)
    resp = client.post("/api/processing/jobs", json={
        "document_id": doc_id,
        "job_type": "invalid_type",
    }, headers=headers)
    assert resp.status_code == 422


def test_create_job_document_not_found():
    headers = _register_and_login("notfound")
    resp = client.post("/api/processing/jobs", json={
        "document_id": str(uuid.uuid4()),
        "job_type": "ocr",
    }, headers=headers)
    assert resp.status_code == 404


def test_create_duplicate_active_job_returns_409():
    headers = _register_and_login("dup")
    doc_id = _upload_document(headers)

    # First job
    r1 = client.post("/api/processing/jobs", json={
        "document_id": doc_id,
        "job_type": "ocr",
    }, headers=headers)
    assert r1.status_code == 201

    # Second job of same type on same document — should fail
    r2 = client.post("/api/processing/jobs", json={
        "document_id": doc_id,
        "job_type": "ocr",
    }, headers=headers)
    assert r2.status_code == 409


def test_create_different_type_same_document_allowed():
    headers = _register_and_login("difftype")
    doc_id = _upload_document(headers)

    r1 = client.post("/api/processing/jobs", json={
        "document_id": doc_id,
        "job_type": "ocr",
    }, headers=headers)
    assert r1.status_code == 201

    r2 = client.post("/api/processing/jobs", json={
        "document_id": doc_id,
        "job_type": "summary",
    }, headers=headers)
    assert r2.status_code == 201


# ---------------------------------------------------------------------------
# List and detail
# ---------------------------------------------------------------------------

def test_list_jobs_returns_paginated():
    headers = _register_and_login("list")
    doc_id = _upload_document(headers)

    client.post("/api/processing/jobs", json={"document_id": doc_id, "job_type": "cleaning"}, headers=headers)
    client.post("/api/processing/jobs", json={"document_id": doc_id, "job_type": "chunking"}, headers=headers)

    resp = client.get("/api/processing/jobs", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 2


def test_get_job_detail_includes_logs():
    headers = _register_and_login("detail")
    doc_id = _upload_document(headers)

    create_resp = client.post("/api/processing/jobs", json={
        "document_id": doc_id,
        "job_type": "embeddings",
    }, headers=headers)
    job_id = create_resp.json()["id"]

    resp = client.get(f"/api/processing/jobs/{job_id}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == job_id
    assert "logs" in data
    assert len(data["logs"]) >= 1  # at minimum a CREATED log


def test_get_job_not_found():
    headers = _register_and_login("notfound2")
    resp = client.get(f"/api/processing/jobs/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Ownership isolation
# ---------------------------------------------------------------------------

def test_cannot_access_another_users_job():
    headers_a = _register_and_login("ownerA")
    headers_b = _register_and_login("ownerB")

    doc_id = _upload_document(headers_a)
    create_resp = client.post("/api/processing/jobs", json={
        "document_id": doc_id,
        "job_type": "timeline",
    }, headers=headers_a)
    job_id = create_resp.json()["id"]

    # User B tries to access User A's job
    resp = client.get(f"/api/processing/jobs/{job_id}", headers=headers_b)
    assert resp.status_code == 403


def test_cannot_cancel_another_users_job():
    headers_a = _register_and_login("cancelOwnerA")
    headers_b = _register_and_login("cancelOwnerB")

    doc_id = _upload_document(headers_a)
    create_resp = client.post("/api/processing/jobs", json={
        "document_id": doc_id,
        "job_type": "analytics",
    }, headers=headers_a)
    job_id = create_resp.json()["id"]

    resp = client.post(f"/api/processing/jobs/{job_id}/cancel", headers=headers_b)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def test_cancel_queued_job():
    headers = _register_and_login("cancel")
    doc_id = _upload_document(headers)

    create_resp = client.post("/api/processing/jobs", json={
        "document_id": doc_id,
        "job_type": "summary",
    }, headers=headers)
    job_id = create_resp.json()["id"]

    cancel_resp = client.post(f"/api/processing/jobs/{job_id}/cancel", headers=headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Active jobs and stats
# ---------------------------------------------------------------------------

def test_active_jobs_endpoint():
    headers = _register_and_login("active")
    doc_id = _upload_document(headers)

    client.post("/api/processing/jobs", json={"document_id": doc_id, "job_type": "ocr"}, headers=headers)

    resp = client.get("/api/processing/jobs/active", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_stats_endpoint():
    headers = _register_and_login("stats")
    resp = client.get("/api/processing/jobs/stats", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "queued" in data
    assert "running" in data
    assert "completed" in data
    assert "failed" in data


def test_jobs_for_document_endpoint():
    headers = _register_and_login("fordoc")
    doc_id = _upload_document(headers)

    client.post("/api/processing/jobs", json={"document_id": doc_id, "job_type": "cleaning"}, headers=headers)

    resp = client.get(f"/api/processing/jobs/document/{doc_id}", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) >= 1
    assert all(j["document_id"] == doc_id for j in items)


# ---------------------------------------------------------------------------
# Dashboard includes processing stats
# ---------------------------------------------------------------------------

def test_dashboard_has_processing_fields():
    headers = _register_and_login("dashproc")
    resp = client.get("/api/dashboard", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "processingQueued" in data
    assert "processingRunning" in data
    assert "processingCompletedToday" in data
    assert "processingFailed" in data
