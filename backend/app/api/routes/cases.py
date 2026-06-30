"""
Cases API — production-ready CRUD for the Case Management module.

All endpoints require authentication. Every query is scoped to the
authenticated user (owner_id = current_user.id) to prevent ID enumeration.
"""

import math
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models import Case, CasePriority, CaseStatus, User
from app.schemas import (
    CaseCreateRequest,
    CaseResponse,
    CaseUpdateRequest,
    MessageResponse,
    PaginatedResponse,
)

router = APIRouter(prefix="/cases", tags=["Cases"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_STATUSES = {s.value for s in CaseStatus}
_VALID_PRIORITIES = {p.value for p in CasePriority}
_SORT_FIELDS = {
    "newest": (Case.created_at, "desc"),
    "oldest": (Case.created_at, "asc"),
    "title": (Case.title, "asc"),
    "title_desc": (Case.title, "desc"),
    "priority": (Case.priority, "desc"),
    "status": (Case.status, "asc"),
    "updated": (Case.updated_at, "desc"),
}


def _get_case_or_404(case_id: UUID, user: User, db: Session) -> Case:
    """Return the case if it belongs to the current user, else raise 404."""
    case = db.query(Case).filter(Case.id == case_id, Case.owner_id == user.id).first()
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case


# ---------------------------------------------------------------------------
# GET /api/cases  — list with search / filter / sort / pagination
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=PaginatedResponse[CaseResponse],
    summary="List cases",
    description="Returns paginated cases owned by the authenticated user. "
                "Supports search, filtering by status/priority, sorting, and pagination.",
)
async def list_cases(
    search: Optional[str] = Query(None, description="Search title, case_number, client_name, court_name"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    priority_filter: Optional[str] = Query(None, alias="priority", description="Filter by priority"),
    archived: Optional[bool] = Query(False, description="Include archived cases"),
    sort: str = Query("newest", description="Sort order: newest|oldest|title|priority|status|updated"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[CaseResponse]:
    q = db.query(Case).filter(Case.owner_id == current_user.id)

    # Archived filter
    if not archived:
        q = q.filter(Case.archived == False)  # noqa: E712
    else:
        q = q.filter(Case.archived == True)  # noqa: E712

    # Search
    if search:
        term = f"%{search}%"
        q = q.filter(
            or_(
                Case.title.ilike(term),
                Case.case_number.ilike(term),
                Case.client_name.ilike(term),
                Case.court_name.ilike(term),
            )
        )

    # Status filter
    if status_filter and status_filter in _VALID_STATUSES:
        q = q.filter(Case.status == status_filter)

    # Priority filter
    if priority_filter and priority_filter in _VALID_PRIORITIES:
        q = q.filter(Case.priority == priority_filter)

    # Sorting
    sort_col, sort_dir = _SORT_FIELDS.get(sort, _SORT_FIELDS["newest"])
    q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    total = q.count()
    total_pages = max(1, math.ceil(total / page_size))
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    return PaginatedResponse[CaseResponse](
        items=[CaseResponse.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# POST /api/cases  — create
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new case",
)
async def create_case(
    payload: CaseCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> CaseResponse:
    # Validate enums
    if payload.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {sorted(_VALID_STATUSES)}")
    if payload.priority not in _VALID_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority. Must be one of: {sorted(_VALID_PRIORITIES)}")

    # Unique case_number check across this user's cases
    if payload.case_number:
        existing = db.query(Case).filter(
            Case.case_number == payload.case_number,
            Case.owner_id == current_user.id,
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A case with this case number already exists",
            )

    case = Case(
        owner_id=current_user.id,
        title=payload.title,
        description=payload.description,
        case_number=payload.case_number,
        court_name=payload.court_name,
        jurisdiction=payload.jurisdiction,
        judge_name=payload.judge_name,
        client_name=payload.client_name,
        opposing_party=payload.opposing_party,
        status=payload.status,
        priority=payload.priority,
        tags=payload.tags,
        notes=payload.notes,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return CaseResponse.model_validate(case)


# ---------------------------------------------------------------------------
# GET /api/cases/{id}  — get by id
# ---------------------------------------------------------------------------

@router.get(
    "/{case_id}",
    response_model=CaseResponse,
    summary="Get case by ID",
)
async def get_case(
    case_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> CaseResponse:
    case = _get_case_or_404(case_id, current_user, db)
    return CaseResponse.model_validate(case)


# ---------------------------------------------------------------------------
# PUT /api/cases/{id}  — full update
# ---------------------------------------------------------------------------

@router.put(
    "/{case_id}",
    response_model=CaseResponse,
    summary="Update a case",
)
async def update_case(
    case_id: UUID,
    payload: CaseUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> CaseResponse:
    case = _get_case_or_404(case_id, current_user, db)
    updates = payload.model_dump(exclude_unset=True)

    if "status" in updates and updates["status"] not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {sorted(_VALID_STATUSES)}")
    if "priority" in updates and updates["priority"] not in _VALID_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority. Must be one of: {sorted(_VALID_PRIORITIES)}")

    # Case number uniqueness check (if changing)
    if "case_number" in updates and updates["case_number"] and updates["case_number"] != case.case_number:
        conflict = db.query(Case).filter(
            Case.case_number == updates["case_number"],
            Case.owner_id == current_user.id,
            Case.id != case_id,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="A case with this case number already exists")

    for field, value in updates.items():
        setattr(case, field, value)

    db.commit()
    db.refresh(case)
    return CaseResponse.model_validate(case)


# ---------------------------------------------------------------------------
# DELETE /api/cases/{id}  — soft delete (archive)
# ---------------------------------------------------------------------------

@router.delete(
    "/{case_id}",
    response_model=MessageResponse,
    summary="Archive (soft-delete) a case",
)
async def delete_case(
    case_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    case = _get_case_or_404(case_id, current_user, db)
    case.archived = True
    db.commit()
    return MessageResponse(message="Case archived successfully")


# ---------------------------------------------------------------------------
# PATCH /api/cases/{id}/archive  — explicitly archive
# ---------------------------------------------------------------------------

@router.patch(
    "/{case_id}/archive",
    response_model=CaseResponse,
    summary="Archive a case",
)
async def archive_case(
    case_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> CaseResponse:
    case = _get_case_or_404(case_id, current_user, db)
    case.archived = True
    db.commit()
    db.refresh(case)
    return CaseResponse.model_validate(case)


# ---------------------------------------------------------------------------
# PATCH /api/cases/{id}/restore  — restore from archive
# ---------------------------------------------------------------------------

@router.patch(
    "/{case_id}/restore",
    response_model=CaseResponse,
    summary="Restore an archived case",
)
async def restore_case(
    case_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> CaseResponse:
    # For restore, we need to look at ALL cases including archived
    case = db.query(Case).filter(Case.id == case_id, Case.owner_id == current_user.id).first()
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    case.archived = False
    db.commit()
    db.refresh(case)
    return CaseResponse.model_validate(case)
