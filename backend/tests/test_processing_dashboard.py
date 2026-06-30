"""
backend/tests/test_processing_dashboard.py — Unit and integration tests for Phase 5.5 operations dashboard.
"""

import io
import time
import uuid
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient
from main import app

from app.processing.service import get_processing_service
from app.models import JobLogEventType, JobStatus, JobType


def _register_and_login(client: TestClient) -> dict:
    uid = uuid.uuid4().hex[:8]
    email = f"ops{uid}@example.com"
    client.post("/api/auth/register", json={
        "email": email,
        "username": f"ops{uid}",
        "password": "password123",
        "full_name": "Operations Manager",
    })
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_case(client: TestClient, headers: dict) -> dict:
    r = client.post("/api/cases", json={"title": "Dashboard Case"}, headers=headers)
    return r.json()


def _upload_document(client: TestClient, headers: dict, case_id: str) -> str:
    files = {"file": ("test.txt", io.BytesIO(b"Sample case text to clean and chunk."), "text/plain")}
    data = {"title": "Dashboard Doc", "case_id": case_id}
    resp = client.post("/api/documents/upload", files=files, data=data, headers=headers)
    return resp.json()["id"]


def test_dashboard_service_and_endpoints():
    with TestClient(app) as test_client:
        headers = _register_and_login(test_client)
        case = _create_case(test_client, headers)
        doc_id = _upload_document(test_client, headers, case["id"])

        # 1. Create a background job to populate queue and stats
        job_resp = test_client.post("/api/processing/jobs", json={
            "document_id": doc_id,
            "job_type": "text_extraction",
        }, headers=headers)
        assert job_resp.status_code == 201
        job_id = job_resp.json()["id"]

        # Wait briefly for worker lifecycle events to write logs
        time.sleep(3.0)

        # 2. GET /processing/stats overview endpoint
        stats_resp = test_client.get("/api/processing/stats", headers=headers)
        assert stats_resp.status_code == 200
        stats = stats_resp.json()
        assert stats["total_jobs"] >= 1
        assert stats["success_rate"] >= 0.0

        # 3. GET /processing/queue health endpoint
        queue_resp = test_client.get("/api/processing/queue", headers=headers)
        assert queue_resp.status_code == 200
        queue = queue_resp.json()
        assert queue["queue_length"] >= 0
        assert queue["active_workers"] == 1
        assert queue["worker_status"] == "healthy"

        # 4. GET /processing/logs terminal list endpoint
        logs_resp = test_client.get("/api/processing/logs", headers=headers)
        assert logs_resp.status_code == 200
        logs = logs_resp.json()
        assert len(logs["items"]) >= 1
        assert logs["total"] >= 1

        # 5. GET /processing/performance analytics endpoint
        perf_resp = test_client.get("/api/processing/performance", headers=headers)
        assert perf_resp.status_code == 200
        perf = perf_resp.json()
        assert "trends" in perf
        assert len(perf["trends"]) >= 1

        # 6. GET /processing/jobs/{id}/timeline pipeline stages endpoint
        timeline_resp = test_client.get(f"/api/processing/jobs/{job_id}/timeline", headers=headers)
        assert timeline_resp.status_code == 200
        timeline = timeline_resp.json()
        assert timeline["job_id"] == job_id
        assert len(timeline["timeline"]) >= 1
        # Reconstructed stages must include Queued & completed stages
        stages = [t["stage"] for t in timeline["timeline"]]
        assert "Queued" in stages

        # 7. GET /processing/jobs/{id}/warnings endpoint
        warnings_resp = test_client.get(f"/api/processing/jobs/{job_id}/warnings", headers=headers)
        assert warnings_resp.status_code == 200
        assert "warnings" in warnings_resp.json()

        # 8. GET /processing/jobs/{id}/metrics duration metrics endpoint
        metrics_resp = test_client.get(f"/api/processing/jobs/{job_id}/metrics", headers=headers)
        assert metrics_resp.status_code == 200
        metrics = metrics_resp.json()
        assert metrics["job_id"] == job_id
        assert "queue_wait_time" in metrics
        assert "worker_execution_time" in metrics
