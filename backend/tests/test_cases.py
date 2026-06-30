"""
Backend tests for Case Management API (Phase 3).
"""

import uuid
from fastapi.testclient import TestClient

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(suffix: str = "") -> dict:
    """Register + login a fresh user, return auth headers."""
    uid = uuid.uuid4().hex[:8]
    email = f"casetest{uid}{suffix}@example.com"
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"casetest{uid}",
        "password": "password123",
        "full_name": "Case Tester",
    })
    assert reg.status_code == 201, reg.text
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_case(headers: dict, **kwargs) -> dict:
    payload = {"title": "Test Case Alpha", "priority": "medium", "status": "open"}
    payload.update(kwargs)
    r = client.post("/api/cases", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

def test_list_cases_requires_auth():
    r = client.get("/api/cases")
    assert r.status_code == 401


def test_create_case_requires_auth():
    r = client.post("/api/cases", json={"title": "No auth case"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------

def test_create_case_success():
    headers = _register_and_login("create")
    uid = uuid.uuid4().hex[:6]
    data = _create_case(
        headers,
        title="Contract Dispute v. Acme Corp",
        case_number=f"CD-{uid}-001",
        court_name="District Court",
        jurisdiction="New York",
        client_name="Jane Smith",
        opposing_party="Acme Corp",
        priority="high",
        status="active",
    )
    assert data["title"] == "Contract Dispute v. Acme Corp"
    assert data["priority"] == "high"
    assert data["status"] == "active"
    assert data["archived"] is False
    assert "id" in data


def test_get_case_success():
    headers = _register_and_login("get")
    case = _create_case(headers, title="Get Me Case")
    r = client.get(f"/api/cases/{case['id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["title"] == "Get Me Case"


def test_list_cases_returns_own_only():
    headers_a = _register_and_login("lista")
    headers_b = _register_and_login("listb")
    _create_case(headers_a, title="User A Case")
    r = client.get("/api/cases", headers=headers_b)
    assert r.status_code == 200
    # User B should see 0 cases
    assert r.json()["total"] == 0


def test_update_case():
    headers = _register_and_login("update")
    case = _create_case(headers, title="Before Update")
    r = client.put(f"/api/cases/{case['id']}", json={"title": "After Update", "status": "active"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["title"] == "After Update"
    assert r.json()["status"] == "active"


def test_update_case_not_owner_returns_404():
    headers_owner = _register_and_login("owner")
    headers_other = _register_and_login("other")
    case = _create_case(headers_owner, title="Owner's Case")
    r = client.put(f"/api/cases/{case['id']}", json={"title": "Hack"}, headers=headers_other)
    assert r.status_code == 404


def test_soft_delete_case():
    headers = _register_and_login("delete")
    case = _create_case(headers, title="To Be Archived")
    r = client.delete(f"/api/cases/{case['id']}", headers=headers)
    assert r.status_code == 200
    # Should no longer appear in default list
    list_r = client.get("/api/cases", headers=headers)
    ids = [c["id"] for c in list_r.json()["items"]]
    assert case["id"] not in ids


def test_restore_case():
    headers = _register_and_login("restore")
    case = _create_case(headers, title="To Restore")
    client.delete(f"/api/cases/{case['id']}", headers=headers)
    r = client.patch(f"/api/cases/{case['id']}/restore", headers=headers)
    assert r.status_code == 200
    assert r.json()["archived"] is False
    # Should reappear in active list
    list_r = client.get("/api/cases", headers=headers)
    ids = [c["id"] for c in list_r.json()["items"]]
    assert case["id"] in ids


# ---------------------------------------------------------------------------
# Search & filter tests
# ---------------------------------------------------------------------------

def test_search_cases():
    headers = _register_and_login("search")
    _create_case(headers, title="Smith vs Jones", client_name="Alice Smith")
    _create_case(headers, title="Unrelated Matter")
    r = client.get("/api/cases?search=Smith", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert any("Smith" in c["title"] or (c.get("client_name") and "Smith" in c["client_name"])
               for c in data["items"])


def test_filter_by_status():
    headers = _register_and_login("filterstatus")
    _create_case(headers, title="Active Case", status="active")
    _create_case(headers, title="Open Case", status="open")
    r = client.get("/api/cases?status=active", headers=headers)
    assert r.status_code == 200
    assert all(c["status"] == "active" for c in r.json()["items"])


def test_filter_by_priority():
    headers = _register_and_login("filterpri")
    _create_case(headers, title="Urgent Case", priority="urgent")
    _create_case(headers, title="Low Case", priority="low")
    r = client.get("/api/cases?priority=urgent", headers=headers)
    assert r.status_code == 200
    assert all(c["priority"] == "urgent" for c in r.json()["items"])


def test_pagination():
    headers = _register_and_login("page")
    for i in range(5):
        _create_case(headers, title=f"Paged Case {i}")
    r = client.get("/api/cases?page=1&page_size=2", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert data["total"] == 5
    assert data["total_pages"] == 3


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

def test_create_case_invalid_status():
    headers = _register_and_login("val")
    r = client.post("/api/cases", json={"title": "Test", "status": "invalid_status"}, headers=headers)
    assert r.status_code == 400


def test_create_case_missing_title():
    headers = _register_and_login("val2")
    r = client.post("/api/cases", json={"priority": "high"}, headers=headers)
    assert r.status_code == 422
