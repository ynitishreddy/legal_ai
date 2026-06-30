from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query

from app.schemas import TimelineEventResponse, TimelineResponse
from app.services.mock_data import MockDataService

router = APIRouter(prefix="/timeline", tags=["Timeline"])


@router.get("", response_model=TimelineResponse, summary="Get timeline events")
async def get_timeline(
    case_id: Optional[UUID] = Query(None),
    event_type: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
) -> TimelineResponse:
    return MockDataService.get_timeline(case_id=case_id)


@router.get("/events/{event_id}", response_model=TimelineEventResponse, summary="Get timeline event")
async def get_event(event_id: UUID) -> TimelineEventResponse:
    from datetime import timezone

    return TimelineEventResponse(
        id=event_id,
        title="Sample Event",
        description="Placeholder timeline event for Phase 1",
        event_date=datetime.now(timezone.utc),
        event_type="hearing",
        confidence_score=None,
        case_id=UUID("00000000-0000-0000-0000-000000000001"),
        document_id=None,
    )
