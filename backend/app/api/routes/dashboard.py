"""
Dashboard API — real DB-backed statistics for the authenticated user.
Replaced MockDataService with actual SQL aggregations (Phase 3).
Extended with processing job stats (Phase 5.1).
"""

from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models import Case, Document, User
from app.processing.service import ProcessingService, get_processing_service
from app.schemas import DashboardStatsResponse

router = APIRouter(tags=["Dashboard"])


@router.get(
    "/dashboard",
    response_model=DashboardStatsResponse,
    summary="Get dashboard statistics",
    description="Returns real aggregate stats for the authenticated user's workspace.",
)
async def get_dashboard(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> DashboardStatsResponse:
    uid = current_user.id

    total_cases = (
        db.query(func.count(Case.id))
        .filter(Case.owner_id == uid, Case.archived == False)  # noqa: E712
        .scalar() or 0
    )
    active_cases = (
        db.query(func.count(Case.id))
        .filter(
            Case.owner_id == uid,
            Case.archived == False,  # noqa: E712
            Case.status.in_(["active", "open"]),
        )
        .scalar() or 0
    )
    closed_cases = (
        db.query(func.count(Case.id))
        .filter(Case.owner_id == uid, Case.status == "closed")
        .scalar() or 0
    )
    archived_cases = (
        db.query(func.count(Case.id))
        .filter(Case.owner_id == uid, Case.archived == True)  # noqa: E712
        .scalar() or 0
    )
    total_documents = (
        db.query(func.count(Document.id))
        .filter(Document.owner_id == uid)
        .scalar() or 0
    )

    # Processing stats (Phase 5.1)
    processing_service = get_processing_service(db)
    processing_stats = processing_service.get_stats(user_id=uid)

    return DashboardStatsResponse(
        totalCases=total_cases,
        totalDocuments=total_documents,
        activeCases=active_cases,
        closedCases=closed_cases,
        archivedCases=archived_cases,
        timelineEvents=0,       # Phase 6: wire real timeline counts
        processingQueued=processing_stats["queued"],
        processingRunning=processing_stats["running"],
        processingCompletedToday=processing_stats["completed_today"],
        processingFailed=processing_stats["failed"],
    )
