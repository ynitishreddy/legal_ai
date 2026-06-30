"""
app.api.routes.processing — REST endpoints for processing job management.

All business logic is delegated to ProcessingService.
Routers are intentionally thin.
"""

import json
import math
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models import User
from app.processing.service import ProcessingService, get_processing_service
from app.schemas import (
    MessageResponse,
    ProcessingJobCreateRequest,
    ProcessingJobDetailResponse,
    ProcessingJobListResponse,
    ProcessingJobResponse,
    ProcessingStatsResponse,
    ProcessingQueueHealthResponse,
    ProcessingLogsListResponse,
    ProcessingPerformanceResponse,
    JobTimelineResponse,
    JobWarningsResponse,
    JobMetricsResponse,
    ProcessingDashboardStatsResponse,
)

router = APIRouter(prefix="/processing", tags=["Processing"])


def _make_service(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> tuple[User, ProcessingService]:
    """Combined dependency: authenticate + create service."""
    return current_user, get_processing_service(db)


# ---------------------------------------------------------------------------
# POST /processing/jobs — Create a new processing job
# ---------------------------------------------------------------------------

@router.post(
    "/jobs",
    response_model=ProcessingJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a processing job",
    description=(
        "Create and enqueue a background processing job for a document. "
        "Returns 409 if an active job of the same type already exists for the document."
    ),
)
async def create_processing_job(
    body: ProcessingJobCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ProcessingJobResponse:
    service = get_processing_service(db)
    job = await service.create_job(
        user_id=current_user.id,
        document_id=body.document_id,
        job_type=body.job_type,
        priority=body.priority,
        max_retries=body.max_retries,
    )
    return ProcessingJobResponse.model_validate(job)


# ---------------------------------------------------------------------------
# GET /processing/jobs/active — Get active jobs for the current user
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/active",
    response_model=List[ProcessingJobResponse],
    summary="Get active processing jobs",
    description="Returns all PENDING, QUEUED, STARTING, and RUNNING jobs for the current user.",
)
def get_active_jobs(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> List[ProcessingJobResponse]:
    service = get_processing_service(db)
    jobs = service.get_active_jobs(user_id=current_user.id)
    return [ProcessingJobResponse.model_validate(j) for j in jobs]


# ---------------------------------------------------------------------------
# GET /processing/jobs/stats — Get processing statistics
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/stats",
    response_model=ProcessingStatsResponse,
    summary="Get processing statistics",
    description="Returns aggregate job counts by status for the current user.",
)
def get_processing_stats(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ProcessingStatsResponse:
    service = get_processing_service(db)
    stats = service.get_stats(user_id=current_user.id)
    return ProcessingStatsResponse(**stats)


# ---------------------------------------------------------------------------
# GET /processing/jobs/document/{document_id} — Jobs for a document
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/document/{document_id}",
    response_model=List[ProcessingJobResponse],
    summary="Get processing jobs for a document",
    description="Returns all processing jobs for a specific document owned by the current user.",
)
def get_jobs_for_document(
    document_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> List[ProcessingJobResponse]:
    service = get_processing_service(db)
    jobs = service.get_jobs_for_document(document_id=document_id, user_id=current_user.id)
    return [ProcessingJobResponse.model_validate(j) for j in jobs]


# ---------------------------------------------------------------------------
# GET /processing/jobs — List jobs (paginated + filtered)
# ---------------------------------------------------------------------------

@router.get(
    "/jobs",
    response_model=ProcessingJobListResponse,
    summary="List processing jobs",
    description="Paginated list of processing jobs for the current user.",
)
def list_processing_jobs(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    job_type_filter: Optional[str] = Query(None, alias="job_type", description="Filter by job type"),
    document_id: Optional[UUID] = Query(None, description="Filter by document"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ProcessingJobListResponse:
    service = get_processing_service(db)
    jobs, total = service.list_jobs(
        user_id=current_user.id,
        status_filter=status_filter,
        job_type_filter=job_type_filter,
        document_id=document_id,
        page=page,
        page_size=page_size,
    )
    return ProcessingJobListResponse(
        items=[ProcessingJobResponse.model_validate(j) for j in jobs],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 0,
    )


# ---------------------------------------------------------------------------
# GET /processing/jobs/{id} — Job detail with logs
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}",
    response_model=ProcessingJobDetailResponse,
    summary="Get processing job details",
    description="Returns full job details including the chronological event log.",
)
def get_processing_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ProcessingJobDetailResponse:
    service = get_processing_service(db)
    job = service.get_job(job_id=job_id, user_id=current_user.id)
    return ProcessingJobDetailResponse.model_validate(job)


# ---------------------------------------------------------------------------
# POST /processing/jobs/{id}/retry — Retry a failed job
# ---------------------------------------------------------------------------

@router.post(
    "/jobs/{job_id}/retry",
    response_model=ProcessingJobResponse,
    summary="Retry a failed processing job",
    description=(
        "Re-queue a FAILED job. "
        "Returns 409 if the job is not in FAILED status or max retries has been reached."
    ),
)
async def retry_processing_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ProcessingJobResponse:
    service = get_processing_service(db)
    job = await service.retry_job(job_id=job_id, user_id=current_user.id)
    return ProcessingJobResponse.model_validate(job)


# ---------------------------------------------------------------------------
# POST /processing/jobs/{id}/cancel — Cancel a job
# ---------------------------------------------------------------------------

@router.post(
    "/jobs/{job_id}/cancel",
    response_model=ProcessingJobResponse,
    summary="Cancel a processing job",
    description=(
        "Cancel a PENDING, QUEUED, STARTING, or RUNNING job. "
        "Returns 409 if the job is already in a terminal status."
    ),
)
async def cancel_processing_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ProcessingJobResponse:
    service = get_processing_service(db)
    job = await service.cancel_job(job_id=job_id, user_id=current_user.id)
    return ProcessingJobResponse.model_validate(job)


# ---------------------------------------------------------------------------
# GET /processing/stats — Operations dashboard overview statistics
# ---------------------------------------------------------------------------

@router.get(
    "/stats",
    response_model=ProcessingDashboardStatsResponse,
    summary="Get dashboard overview statistics",
)
def get_dashboard_stats(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ProcessingDashboardStatsResponse:
    service = get_processing_service(db)
    stats = service.get_dashboard_stats(user_id=current_user.id)
    return ProcessingDashboardStatsResponse(**stats)


# ---------------------------------------------------------------------------
# GET /processing/queue — Queue Health monitoring
# ---------------------------------------------------------------------------

@router.get(
    "/queue",
    response_model=ProcessingQueueHealthResponse,
    summary="Get queue health metrics",
)
async def get_queue_health(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ProcessingQueueHealthResponse:
    service = get_processing_service(db)
    health = await service.get_queue_health()
    return ProcessingQueueHealthResponse(**health)


# ---------------------------------------------------------------------------
# GET /processing/logs — Searchable, paginated event logs
# ---------------------------------------------------------------------------

@router.get(
    "/logs",
    response_model=ProcessingLogsListResponse,
    summary="Get system event logs",
)
def get_dashboard_logs(
    search: Optional[str] = Query(None, description="Search term"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ProcessingLogsListResponse:
    service = get_processing_service(db)
    logs, total = service.get_dashboard_logs(
        user_id=current_user.id,
        search=search,
        event_type=event_type,
        page=page,
        page_size=page_size,
    )
    # Parse event logs to schema format
    items = []
    for l in logs:
        meta = {}
        if l.metadata_json:
            try:
                meta = json.loads(l.metadata_json)
            except Exception:
                pass
        items.append({
            "id": l.id,
            "job_id": l.job_id,
            "timestamp": l.created_at,
            "event_type": l.event_type.value if hasattr(l.event_type, "value") else str(l.event_type),
            "message": l.message,
            "metadata": meta,
        })
    return ProcessingLogsListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /processing/health — Health check (aliases queue health)
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    response_model=ProcessingQueueHealthResponse,
    summary="Alias to get queue health check",
)
async def get_processing_health(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ProcessingQueueHealthResponse:
    service = get_processing_service(db)
    health = await service.get_queue_health()
    return ProcessingQueueHealthResponse(**health)


# ---------------------------------------------------------------------------
# GET /processing/performance — Processing performance indicators & charts
# ---------------------------------------------------------------------------

@router.get(
    "/performance",
    response_model=ProcessingPerformanceResponse,
    summary="Get performance indicators & chart trends",
)
def get_performance_analytics(
    period_days: int = Query(7, ge=1, le=30),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ProcessingPerformanceResponse:
    service = get_processing_service(db)
    analytics = service.get_performance_analytics(user_id=current_user.id, period_days=period_days)
    return ProcessingPerformanceResponse(**analytics)


# ---------------------------------------------------------------------------
# GET /processing/jobs/{id}/timeline — Reconstructed pipeline stages timeline
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}/timeline",
    response_model=JobTimelineResponse,
    summary="Get job pipeline timeline history",
)
def get_job_timeline(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JobTimelineResponse:
    service = get_processing_service(db)
    timeline = service.get_job_timeline(job_id=job_id, user_id=current_user.id)
    return JobTimelineResponse(**timeline)


# ---------------------------------------------------------------------------
# GET /processing/jobs/{id}/warnings — Job-specific warning aggregates
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}/warnings",
    response_model=JobWarningsResponse,
    summary="Get job pipeline warnings",
)
def get_job_warnings(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JobWarningsResponse:
    service = get_processing_service(db)
    warnings = service.get_job_warnings(job_id=job_id, user_id=current_user.id)
    return JobWarningsResponse(job_id=job_id, warnings=warnings)


# ---------------------------------------------------------------------------
# GET /processing/jobs/{id}/metrics — Job-specific wait/execution duration metrics
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}/metrics",
    response_model=JobMetricsResponse,
    summary="Get job performance metrics",
)
def get_job_metrics(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> JobMetricsResponse:
    service = get_processing_service(db)
    metrics = service.get_job_metrics(job_id=job_id, user_id=current_user.id)
    return JobMetricsResponse(**metrics)

