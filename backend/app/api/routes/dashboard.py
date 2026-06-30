"""
Dashboard API — real DB-backed statistics for the authenticated user.
Replaced MockDataService with actual SQL aggregations (Phase 3).
"""

from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models import Case, User
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

    return DashboardStatsResponse(
        totalCases=total_cases,
        totalDocuments=0,       # Phase 4: wire real document counts
        activeCases=active_cases,
        closedCases=closed_cases,
        archivedCases=archived_cases,
        timelineEvents=0,       # Phase 4: wire real timeline counts
    )
