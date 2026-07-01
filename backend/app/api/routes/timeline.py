import logging
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User, TimelineEvent
from app.api.deps import get_current_active_user
from app.schemas.timeline import (
    TimelineExtractionRequest,
    TimelineRebuildRequest,
    LegalEventResponse,
    TimelineStatsResponse,
)
from app.services.timeline import TimelineIntelligenceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/timeline", tags=["Timeline"])


# 1. POST /api/timeline/extract -> Trigger single extraction
@router.post(
    "/extract",
    response_model=List[LegalEventResponse],
    status_code=status.HTTP_201_CREATED,
)
async def extract_timeline_events(
    payload: TimelineExtractionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = TimelineIntelligenceService(db)
    try:
        events = service.extract_document_events(payload.case_id, payload.document_id)
        # Map to LegalEventResponse list structure
        return service.get_case_timeline(payload.case_id)
    except Exception as e:
        logger.error("TimelineRoute: Extraction failed: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Extraction failed: {str(e)}"
        )


# 2. GET /api/timeline/case/{id} -> Case timeline list
@router.get(
    "/case/{case_id}",
    response_model=List[LegalEventResponse],
)
async def get_case_timeline_endpoint(
    case_id: UUID,
    event_type: Optional[str] = Query(None),
    min_confidence: Optional[float] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = TimelineIntelligenceService(db)
    return service.get_case_timeline(
        case_id=case_id,
        event_type=event_type,
        min_confidence=min_confidence
    )


# 3. GET /api/timeline/document/{id} -> Document specific events list
@router.get(
    "/document/{document_id}",
    response_model=List[LegalEventResponse],
)
async def get_document_timeline_endpoint(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    events = (
        db.query(TimelineEvent)
        .filter(TimelineEvent.document_id == document_id)
        .order_by(TimelineEvent.normalized_date.asc())
        .all()
    )
    service = TimelineIntelligenceService(db)
    case_id = events[0].case_id if events else None
    if not case_id:
        return []
    
    timeline = service.get_case_timeline(case_id)
    return [e for e in timeline if e["document_id"] == str(document_id)]


# 4. GET /api/timeline/event/{id} -> Single event detail
@router.get(
    "/event/{event_id}",
    response_model=LegalEventResponse,
)
async def get_event_detail_endpoint(
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    event = db.get(TimelineEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    
    service = TimelineIntelligenceService(db)
    timeline = service.get_case_timeline(event.case_id)
    match = [e for e in timeline if e["id"] == str(event_id)]
    if not match:
        raise HTTPException(status_code=404, detail="Event matching not found.")
    return match[0]


# 5. GET /api/timeline/search -> Search timeline query matches
@router.get(
    "/search",
    response_model=List[LegalEventResponse],
)
async def search_timeline_endpoint(
    query: str = Query(...),
    case_id: UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = TimelineIntelligenceService(db)
    timeline = service.get_case_timeline(case_id)
    q = query.lower()
    
    return [
        e for e in timeline
        if q in e["event_title"].lower() or q in e["event_description"].lower()
    ]


# 6. POST /api/timeline/rebuild -> Enforce full case timeline rebuild
@router.post(
    "/rebuild",
    status_code=status.HTTP_200_OK,
)
async def rebuild_timeline_endpoint(
    payload: TimelineRebuildRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = TimelineIntelligenceService(db)
    try:
        service.rebuild_case_timeline(payload.case_id)
        return {"success": True, "message": "Case timeline rebuilt successfully."}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Rebuild failed: {str(e)}"
        )


# 7. GET /api/timeline/statistics -> Case timeline statistics
@router.get(
    "/statistics",
    response_model=TimelineStatsResponse,
)
async def get_timeline_statistics_endpoint(
    case_id: UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    service = TimelineIntelligenceService(db)
    return service.get_timeline_statistics(case_id)
