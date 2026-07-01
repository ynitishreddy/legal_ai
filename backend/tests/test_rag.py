import uuid
import json
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from main import app
from app.db.session import SessionLocal
from app.core.config import get_settings
from app.models import User, ChatSession, ChatMessage, ChatRole
from app.document_processing.models import DocumentChunk
from app.services.rag import RAGService, estimate_cost
from app.services.llm import LLMService, MockLLMAdapter
from app.services.prompt_builder import PromptBuilder
from app.services.retriever import RetrieverService

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
    email = f"auth_rag_{uid}@example.com"
    
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"auth_rag_{uid}",
        "password": "password123",
        "full_name": "Auth RAG Tester",
    })
    assert reg.status_code == 201
    
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    
    db_user = db_session.query(User).filter(User.email == email).first()
    
    yield {"headers": {"Authorization": f"Bearer {token}"}, "user_id": db_user.id}
    
    # Cleanup session logs
    db_session.query(ChatMessage).filter(ChatMessage.session_id.in_(
        db_session.query(ChatSession.id).filter(ChatSession.user_id == db_user.id)
    )).delete(synchronize_session=False)
    db_session.query(ChatSession).filter(ChatSession.user_id == db_user.id).delete(synchronize_session=False)
    db_session.delete(db_user)
    db_session.commit()


def test_estimate_cost():
    cost_gpt4o = estimate_cost("openai", "gpt-4o", 1000, 500)
    assert cost_gpt4o == (1000 * 0.005 + 500 * 0.015) / 1000.0

    cost_gemini_flash = estimate_cost("gemini", "gemini-1.5-flash", 1000, 500)
    assert cost_gemini_flash == (1000 * 0.000375 + 500 * 0.00115) / 1000.0


def test_llm_adapter_selection():
    svc = LLMService()
    
    # Fallback to mock adapter when api keys are not provided
    adapter = svc.get_adapter(provider="openai")
    assert isinstance(adapter, MockLLMAdapter) or type(adapter).__name__ == "OpenAIAdapter"

    mock_adapter = svc.get_adapter(provider="mock")
    assert isinstance(mock_adapter, MockLLMAdapter)
    assert mock_adapter.health_check() is True


def test_prompt_builder():
    builder = PromptBuilder()
    sys_prompt = builder.build_system_prompt()
    assert "GROUNDING RULE" in sys_prompt
    
    prompt = builder.build_prompt("User query here", "Snippet document details.")
    assert "=== BEGIN CONTEXT ===" in prompt
    assert "User query here" in prompt
    # Verify escaping of code markdown
    prompt_inj = builder.build_prompt("query", "Inject ``` commands")
    assert "Inject ''' commands" in prompt_inj


def test_rag_pipeline_execution(db_session: Session, auth_headers: dict, monkeypatch):
    user_id = auth_headers["user_id"]
    service = RAGService(db_session)
    
    session_id = uuid.uuid4()
    
    # Mock retrieval service
    monkeypatch.setattr(
        RetrieverService,
        "retrieve_semantic",
        lambda *args, **kwargs: [
            {
                "chunk_id": "chunk-infringement-id",
                "document_id": str(uuid.uuid4()),
                "document_name": "license.pdf",
                "page_number": 1,
                "section_title": "Scope",
                "similarity_score": 0.95,
                "source_path": "uploads/license.pdf",
                "text": "Proprietary modules are licensed strictly.",
                "chunk_index": 1,
            }
        ]
    )

    # Perform query RAG
    msg = service.query_rag(
        session_id=session_id,
        user_id=user_id,
        question="Is copyright infringement present?",
        provider="mock",
    )

    assert msg.role == ChatRole.ASSISTANT
    assert "defendant software incorporates" in msg.content
    assert "citations_json" in msg.__dict__
    
    citations = json.loads(msg.citations_json)
    assert len(citations) == 1
    assert citations[0]["chunk_id"] == "chunk-infringement-id"


def test_chat_api_routes(db_session: Session, auth_headers: dict, monkeypatch):
    user_id = auth_headers["user_id"]
    headers = auth_headers["headers"]
    
    session_id = uuid.uuid4()
    
    # Mock class-level retrieval service to resolve contexts for routes
    monkeypatch.setattr(
        RetrieverService,
        "retrieve_semantic",
        lambda *args, **kwargs: [
            {
                "chunk_id": "chunk-infringement-id",
                "document_id": str(uuid.uuid4()),
                "document_name": "license.pdf",
                "page_number": 1,
                "section_title": "Scope",
                "similarity_score": 0.95,
                "source_path": "uploads/license.pdf",
                "text": "Proprietary modules are licensed strictly.",
                "chunk_index": 1,
            }
        ]
    )

    # 1. Test POST /api/chat/message (Generate RAG Answer)
    res_msg = client.post(
        "/api/chat/message",
        json={
            "content": "Is copyright infringement present?",
            "session_id": str(session_id),
            "provider": "mock",
        },
        headers=headers,
    )
    assert res_msg.status_code == 201
    data = res_msg.json()
    assert data["session_id"] == str(session_id)
    assert "defendant software incorporates" in data["assistant_message"]["content"]

    # 2. Test GET /api/chat/sessions (List sessions)
    res_sessions = client.get("/api/chat/sessions", headers=headers)
    assert res_sessions.status_code == 200
    assert len(res_sessions.json()["sessions"]) >= 1

    # 3. Test GET /api/chat/sessions/{id}
    res_sess_info = client.get(f"/api/chat/sessions/{session_id}", headers=headers)
    assert res_sess_info.status_code == 200
    assert res_sess_info.json()["title"] is not None

    # 4. Test GET /api/chat/messages/{session_id}
    res_msgs = client.get(f"/api/chat/messages/{session_id}", headers=headers)
    assert res_msgs.status_code == 200
    assert len(res_msgs.json()) == 2 # user + assistant

    # 5. Test GET /api/chat/providers
    res_prov = client.get("/api/chat/providers", headers=headers)
    assert res_prov.status_code == 200
    assert len(res_prov.json()) >= 1

    # 6. Test GET /api/chat/models
    res_models = client.get("/api/chat/models", headers=headers)
    assert res_models.status_code == 200
    assert len(res_models.json()) >= 1

    # 7. Test GET /api/chat/health
    res_health = client.get("/api/chat/health", headers=headers)
    assert res_health.status_code == 200
    assert res_health.json()["status"] is not None

    # 8. Test GET /api/chat/statistics
    res_stats = client.get("/api/chat/statistics", headers=headers)
    assert res_stats.status_code == 200
    assert res_stats.json()["total_chats"] == 1

    # 9. Test POST /api/chat/stream
    res_stream = client.post(
        "/api/chat/stream",
        json={
            "content": "Is copyright infringement present?",
            "session_id": str(session_id),
            "provider": "mock",
        },
        headers=headers,
    )
    assert res_stream.status_code == 200
    assert "text/event-stream" in res_stream.headers["content-type"]

    # 10. Test DELETE /api/chat/session/{id}
    res_del = client.delete(f"/api/chat/session/{session_id}", headers=headers)
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True
