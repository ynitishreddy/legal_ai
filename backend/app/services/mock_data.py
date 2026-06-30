from uuid import uuid4

from app.schemas import (
    AnalyticsOverviewResponse,
    ChatHistoryResponse,
    ChatMessageResponse,
    ChatQueryResponse,
    ChatSessionResponse,
    DashboardStatsResponse,
    DocumentResponse,
    DocumentUploadResponse,
    PaginatedResponse,
    TimelineEventResponse,
    TimelineResponse,
    TokenResponse,
    UserResponse,
)


class MockDataService:
    """Phase 1 mock data provider. Replace with DB-backed services in Phase 2."""

    MOCK_USER_ID = uuid4()

    @staticmethod
    def get_dashboard_stats() -> DashboardStatsResponse:
        return DashboardStatsResponse(
            totalCases=0,
            totalDocuments=0,
            activeCases=0,
            timelineEvents=0,
        )

    @staticmethod
    def get_documents(page: int = 1, page_size: int = 10) -> PaginatedResponse[DocumentResponse]:
        return PaginatedResponse[DocumentResponse](
            items=[],
            total=0,
            page=page,
            page_size=page_size,
            total_pages=0,
        )

    @staticmethod
    def upload_document(filename: str, title: str | None = None) -> DocumentUploadResponse:
        doc_id = uuid4()
        return DocumentUploadResponse(
            id=doc_id,
            title=title or filename,
            filename=filename,
            status="uploaded",
            message="Document uploaded successfully (mock). Processing will begin in Phase 2.",
        )

    @staticmethod
    def get_timeline(case_id=None) -> TimelineResponse:
        return TimelineResponse(events=[], total=0, case_id=case_id)

    @staticmethod
    def get_chat_sessions() -> ChatHistoryResponse:
        return ChatHistoryResponse(sessions=[], total=0)

    @staticmethod
    def send_chat_message(content: str, session_id=None) -> ChatQueryResponse:
        sid = session_id or uuid4()
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        user_msg = ChatMessageResponse(
            id=uuid4(),
            content=content,
            role="user",
            session_id=sid,
            created_at=now,
        )
        assistant_msg = ChatMessageResponse(
            id=uuid4(),
            content="This is a mock response. LLM integration will be available in Phase 2.",
            role="assistant",
            session_id=sid,
            created_at=now,
        )
        return ChatQueryResponse(
            session_id=sid,
            user_message=user_msg,
            assistant_message=assistant_msg,
        )

    @staticmethod
    def get_analytics() -> AnalyticsOverviewResponse:
        return AnalyticsOverviewResponse(
            metrics=[
                {"name": "Total Cases", "value": 0, "unit": "cases", "change_percent": 0, "trend": "neutral"},
                {"name": "Documents Processed", "value": 0, "unit": "docs", "change_percent": 0, "trend": "neutral"},
                {"name": "Timeline Events", "value": 0, "unit": "events", "change_percent": 0, "trend": "neutral"},
                {"name": "Chat Queries", "value": 0, "unit": "queries", "change_percent": 0, "trend": "neutral"},
            ],
            charts=[
                {
                    "title": "Cases by Status",
                    "chart_type": "pie",
                    "data": [
                        {"label": "Active", "value": 0},
                        {"label": "Pending", "value": 0},
                        {"label": "Closed", "value": 0},
                    ],
                },
                {
                    "title": "Documents Over Time",
                    "chart_type": "line",
                    "data": [],
                },
            ],
            summary={
                "total_cases": 0,
                "total_documents": 0,
                "total_events": 0,
                "processing_success_rate": 0.0,
            },
        )

    @staticmethod
    def get_current_user() -> UserResponse:
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        return UserResponse(
            id=MockDataService.MOCK_USER_ID,
            email="demo@chronolegal.ai",
            username="demo_user",
            full_name="Demo User",
            role="user",
            is_active=True,
            is_verified=True,
            avatar_url=None,
            created_at=now,
        )

    @staticmethod
    def get_auth_tokens() -> TokenResponse:
        return TokenResponse(
            access_token="mock_access_token_phase1",
            refresh_token="mock_refresh_token_phase1",
            token_type="bearer",
            expires_in=1800,
        )
