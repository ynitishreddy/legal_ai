import uuid
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _register_and_login() -> dict:
    uid = uuid.uuid4().hex[:8]
    email = f"apitest{uid}@example.com"
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"apitest{uid}",
        "password": "password123",
        "full_name": "API Tester",
    })
    assert reg.status_code == 201, reg.text
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_dashboard_stats():
    headers = _register_and_login()
    response = client.get("/api/dashboard", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "totalCases" in data
    assert "totalDocuments" in data
    assert data["totalCases"] == 0


def test_auth_login():
    uid = uuid.uuid4().hex[:8]
    email = f"loginonly{uid}@example.com"
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"loginonly{uid}",
        "password": "password123",
        "full_name": "Login Tester",
    })
    assert reg.status_code == 201
    
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


def test_documents_list():
    headers = _register_and_login()
    response = client.get("/api/documents", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 0
