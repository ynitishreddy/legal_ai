"""
app.processing.service — ProcessingService

Business logic for creating, managing, and querying background processing jobs.
All database mutation happens here; routers stay thin.

Key responsibilities:
  - Create & validate jobs (duplicate prevention)
  - Transition job status through the state machine
  - Update progress and write chronological logs
  - Retry and cancel with ownership enforcement
  - Provide query helpers for routers and the dashboard
"""

import json
import logging
import math
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models import (
    Document,
    JobLogEventType,
    JobPriority,
    JobStatus,
    JobType,
    ProcessingJob,
    ProcessingJobLog,
    utcnow,
)
from app.processing.queue import AbstractProcessingQueue, processing_queue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status transition rules
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = {JobStatus.PENDING, JobStatus.QUEUED, JobStatus.STARTING, JobStatus.RUNNING}
_TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


class ProcessingService:
    """
    Service layer for processing job lifecycle management.

    Inject via FastAPI Depends; the queue is provided at construction time
    so it can be swapped in tests or when migrating to Redis/Celery.
    """

    def __init__(self, db: Session, queue: AbstractProcessingQueue = processing_queue) -> None:
        self.db = db
        self.queue = queue

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _get_owned_job(self, job_id: UUID, user_id: UUID) -> ProcessingJob:
        """Fetch a job that belongs to user_id or raise 404/403."""
        job: Optional[ProcessingJob] = self.db.get(ProcessingJob, job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processing job not found")
        if job.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        return job

    def _add_log(
        self,
        job: ProcessingJob,
        event_type: JobLogEventType,
        message: str,
        metadata: Optional[dict] = None,
    ) -> ProcessingJobLog:
        """Append a log entry to the job's event history."""
        log = ProcessingJobLog(
            job_id=job.id,
            event_type=event_type,
            message=message,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        self.db.add(log)
        return log

    # ── Create ───────────────────────────────────────────────────────────────

    async def create_job(
        self,
        user_id: UUID,
        document_id: UUID,
        job_type: str,
        priority: str = "normal",
        max_retries: int = 3,
    ) -> ProcessingJob:
        """
        Create a new processing job and enqueue it.

        Raises 404 if the document does not exist or belongs to another user.
        Raises 409 if an active job of the same type already exists for the document.
        """
        # Verify document ownership
        doc: Optional[Document] = self.db.get(Document, document_id)
        if doc is None or doc.owner_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        # Duplicate prevention: check for active job with same document + type
        existing = (
            self.db.query(ProcessingJob)
            .filter(
                ProcessingJob.document_id == document_id,
                ProcessingJob.job_type == JobType(job_type),
                ProcessingJob.status.in_(list(_ACTIVE_STATUSES)),
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An active {job_type} job already exists for this document (id={existing.id})",
            )

        job = ProcessingJob(
            user_id=user_id,
            document_id=document_id,
            case_id=doc.case_id,
            job_type=JobType(job_type),
            priority=JobPriority(priority),
            status=JobStatus.PENDING,
            max_retries=max_retries,
        )
        self.db.add(job)
        self.db.flush()  # get id without committing

        self._add_log(job, JobLogEventType.CREATED, f"Job created: type={job_type}, priority={priority}")
        self.db.commit()
        self.db.refresh(job)

        # Enqueue immediately
        await self._enqueue_job(job)
        logger.info("ProcessingService.create_job: job=%s type=%s doc=%s", job.id, job_type, document_id)
        return job

    async def _enqueue_job(self, job: ProcessingJob) -> None:
        """Transition job to QUEUED and add to the queue."""
        job.status = JobStatus.QUEUED
        self._add_log(job, JobLogEventType.QUEUED, "Job added to processing queue")
        self.db.commit()
        await self.queue.enqueue(job.id)

    # ── Status transitions (called by the worker) ─────────────────────────────

    def mark_starting(self, job_id: UUID) -> ProcessingJob:
        """Transition QUEUED → STARTING. Called by worker when it picks up a job."""
        job: Optional[ProcessingJob] = self.db.get(ProcessingJob, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        job.status = JobStatus.STARTING
        job.current_step = "Initializing"
        self._add_log(job, JobLogEventType.STARTED, "Worker picked up job — starting")
        self.db.commit()
        return job

    def mark_running(self, job_id: UUID) -> ProcessingJob:
        """Transition STARTING → RUNNING. Called by worker when processing begins."""
        job: Optional[ProcessingJob] = self.db.get(ProcessingJob, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        job.status = JobStatus.RUNNING
        job.started_at = utcnow()
        job.current_step = "Processing"
        self._add_log(job, JobLogEventType.INFO, "Processing started")
        self.db.commit()
        return job

    def update_progress(
        self,
        job_id: UUID,
        percentage: int,
        current_step: str,
        metadata: Optional[dict] = None,
    ) -> ProcessingJob:
        """Update progress percentage and current step. Called by worker periodically."""
        job: Optional[ProcessingJob] = self.db.get(ProcessingJob, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        job.progress_percentage = max(0, min(100, percentage))
        job.current_step = current_step
        self._add_log(
            job,
            JobLogEventType.PROGRESS,
            f"Progress: {percentage}% — {current_step}",
            metadata=metadata,
        )
        self.db.commit()
        return job

    def mark_completed(self, job_id: UUID) -> ProcessingJob:
        """Transition any active status → COMPLETED."""
        job: Optional[ProcessingJob] = self.db.get(ProcessingJob, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        job.status = JobStatus.COMPLETED
        job.progress_percentage = 100
        job.current_step = "Completed"
        job.completed_at = utcnow()
        self._add_log(job, JobLogEventType.COMPLETED, "Job completed successfully")
        self.db.commit()
        logger.info("ProcessingService.mark_completed: job=%s", job_id)
        return job

    def mark_failed(self, job_id: UUID, error_message: str, error_detail: Optional[str] = None) -> ProcessingJob:
        """Transition any active status → FAILED. Stores error information."""
        job: Optional[ProcessingJob] = self.db.get(ProcessingJob, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        job.status = JobStatus.FAILED
        job.error_message = error_message
        job.error_detail = error_detail
        job.completed_at = utcnow()
        self._add_log(
            job,
            JobLogEventType.FAILED,
            f"Job failed: {error_message}",
            metadata={"error_detail": error_detail} if error_detail else None,
        )
        self.db.commit()
        logger.warning("ProcessingService.mark_failed: job=%s error=%s", job_id, error_message)
        return job

    # ── User-initiated actions ─────────────────────────────────────────────────

    async def cancel_job(self, job_id: UUID, user_id: UUID) -> ProcessingJob:
        """Cancel a job that belongs to user_id."""
        job = self._get_owned_job(job_id, user_id)
        if job.status in _TERMINAL_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot cancel a job in terminal status: {job.status.value}",
            )
        # Remove from queue if it hasn't been picked up yet
        await self.queue.cancel(job.id)
        job.status = JobStatus.CANCELLED
        job.completed_at = utcnow()
        self._add_log(job, JobLogEventType.CANCELLED, "Job cancelled by user")
        self.db.commit()
        logger.info("ProcessingService.cancel_job: job=%s user=%s", job_id, user_id)
        return job

    async def retry_job(self, job_id: UUID, user_id: UUID) -> ProcessingJob:
        """
        Retry a FAILED job.

        Raises 409 if the job is not in FAILED status.
        Raises 409 if max_retries has been reached.
        """
        job = self._get_owned_job(job_id, user_id)
        if job.status != JobStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Only FAILED jobs can be retried (current status: {job.status.value})",
            )
        if job.retry_count >= job.max_retries:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Max retries ({job.max_retries}) reached — cannot retry",
            )

        job.retry_count += 1
        job.last_retry_at = utcnow()
        job.status = JobStatus.QUEUED
        job.error_message = None
        job.progress_percentage = 0
        job.current_step = None
        job.started_at = None
        job.completed_at = None

        self._add_log(
            job,
            JobLogEventType.RETRY,
            f"Retry #{job.retry_count} of {job.max_retries} — re-queuing job",
        )
        self.db.commit()

        await self.queue.retry(job.id)
        logger.info("ProcessingService.retry_job: job=%s retry=%d/%d", job_id, job.retry_count, job.max_retries)
        return job

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_job(self, job_id: UUID, user_id: UUID) -> ProcessingJob:
        """Fetch a job with ownership check."""
        return self._get_owned_job(job_id, user_id)

    def list_jobs(
        self,
        user_id: UUID,
        status_filter: Optional[str] = None,
        job_type_filter: Optional[str] = None,
        document_id: Optional[UUID] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[ProcessingJob], int]:
        """Return paginated list of jobs for a user with optional filters."""
        q = self.db.query(ProcessingJob).filter(ProcessingJob.user_id == user_id)

        if status_filter:
            q = q.filter(ProcessingJob.status == JobStatus(status_filter))
        if job_type_filter:
            q = q.filter(ProcessingJob.job_type == JobType(job_type_filter))
        if document_id:
            q = q.filter(ProcessingJob.document_id == document_id)

        total = q.count()
        jobs = (
            q.order_by(ProcessingJob.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return jobs, total

    def get_active_jobs(self, user_id: UUID) -> List[ProcessingJob]:
        """Return all QUEUED/STARTING/RUNNING jobs for a user."""
        return (
            self.db.query(ProcessingJob)
            .filter(
                ProcessingJob.user_id == user_id,
                ProcessingJob.status.in_(list(_ACTIVE_STATUSES)),
            )
            .order_by(ProcessingJob.created_at.asc())
            .all()
        )

    def get_jobs_for_document(self, document_id: UUID, user_id: UUID) -> List[ProcessingJob]:
        """Return all jobs for a specific document, verifying ownership."""
        # Verify document ownership
        doc: Optional[Document] = self.db.get(Document, document_id)
        if doc is None or doc.owner_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return (
            self.db.query(ProcessingJob)
            .filter(ProcessingJob.document_id == document_id)
            .order_by(ProcessingJob.created_at.desc())
            .all()
        )

    def get_stats(self, user_id: UUID) -> dict:
        """Return aggregate job counts for the dashboard."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        rows = (
            self.db.query(ProcessingJob.status, func.count(ProcessingJob.id))
            .filter(ProcessingJob.user_id == user_id)
            .group_by(ProcessingJob.status)
            .all()
        )
        counts = {row[0].value: row[1] for row in rows}

        completed_today = (
            self.db.query(func.count(ProcessingJob.id))
            .filter(
                ProcessingJob.user_id == user_id,
                ProcessingJob.status == JobStatus.COMPLETED,
                ProcessingJob.completed_at >= today_start,
            )
            .scalar() or 0
        )

        # Average duration for completed jobs (seconds)
        avg_duration = (
            self.db.query(
                func.avg(
                    func.extract("epoch", ProcessingJob.completed_at)
                    - func.extract("epoch", ProcessingJob.started_at)
                )
            )
            .filter(
                ProcessingJob.user_id == user_id,
                ProcessingJob.status == JobStatus.COMPLETED,
                ProcessingJob.started_at.isnot(None),
                ProcessingJob.completed_at.isnot(None),
            )
            .scalar()
        )

        return {
            "pending": counts.get("pending", 0),
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0) + counts.get("starting", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
            "completed_today": completed_today,
            "average_duration_seconds": round(float(avg_duration), 2) if avg_duration else None,
        }

    def get_dashboard_stats(self, user_id: UUID) -> dict:
        from app.models import AnalyticsRecord

        rows = (
            self.db.query(ProcessingJob.status, func.count(ProcessingJob.id))
            .filter(ProcessingJob.user_id == user_id)
            .group_by(ProcessingJob.status)
            .all()
        )
        counts = {row[0].value if hasattr(row[0], "value") else str(row[0]): row[1] for row in rows}

        total_jobs = sum(counts.values())
        queued = counts.get("queued", 0) + counts.get("pending", 0)
        running = counts.get("running", 0) + counts.get("starting", 0)
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)

        terminal_jobs = completed + failed + cancelled
        success_rate = (completed / terminal_jobs * 100) if terminal_jobs > 0 else 100.0

        avg_proc = (
            self.db.query(func.avg(AnalyticsRecord.metric_value))
            .filter(
                AnalyticsRecord.user_id == user_id,
                AnalyticsRecord.metric_name == "total_processing_duration"
            )
            .scalar()
        )
        if avg_proc is None:
            avg_proc = (
                self.db.query(
                    func.avg(
                        func.extract("epoch", ProcessingJob.completed_at)
                        - func.extract("epoch", ProcessingJob.started_at)
                    )
                )
                .filter(
                    ProcessingJob.user_id == user_id,
                    ProcessingJob.status == JobStatus.COMPLETED,
                    ProcessingJob.started_at.isnot(None),
                    ProcessingJob.completed_at.isnot(None),
                )
                .scalar()
            )

        avg_queue = (
            self.db.query(func.avg(AnalyticsRecord.metric_value))
            .filter(
                AnalyticsRecord.user_id == user_id,
                AnalyticsRecord.metric_name == "queue_wait_time"
            )
            .scalar()
        )
        if avg_queue is None:
            avg_queue = (
                self.db.query(
                    func.avg(
                        func.extract("epoch", ProcessingJob.started_at)
                        - func.extract("epoch", ProcessingJob.created_at)
                    )
                )
                .filter(
                    ProcessingJob.user_id == user_id,
                    ProcessingJob.started_at.isnot(None),
                )
                .scalar()
            )

        return {
            "total_jobs": total_jobs,
            "queued": queued,
            "running": running,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "success_rate": round(float(success_rate), 2),
            "average_processing_time": round(float(avg_proc), 2) if avg_proc else 0.0,
            "average_queue_time": round(float(avg_queue), 2) if avg_queue else 0.0,
        }

    async def get_queue_health(self) -> dict:
        from app.models import AnalyticsRecord

        queue_len = await self.queue.size()

        waiting_jobs = (
            self.db.query(func.count(ProcessingJob.id))
            .filter(ProcessingJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED]))
            .scalar() or 0
        )

        running_jobs = (
            self.db.query(func.count(ProcessingJob.id))
            .filter(ProcessingJob.status.in_([JobStatus.STARTING, JobStatus.RUNNING]))
            .scalar() or 0
        )

        avg_wait = (
            self.db.query(func.avg(AnalyticsRecord.metric_value))
            .filter(AnalyticsRecord.metric_name == "queue_wait_time")
            .scalar() or 0.0
        )

        avg_proc = (
            self.db.query(func.avg(AnalyticsRecord.metric_value))
            .filter(AnalyticsRecord.metric_name == "worker_execution_time")
            .scalar() or 0.0
        )

        retry_count = (
            self.db.query(func.sum(ProcessingJob.retry_count))
            .scalar() or 0
        )

        failed_jobs = (
            self.db.query(func.count(ProcessingJob.id))
            .filter(ProcessingJob.status == JobStatus.FAILED)
            .scalar() or 0
        )

        return {
            "queue_length": queue_len,
            "active_workers": 1,
            "waiting_jobs": waiting_jobs,
            "running_jobs": running_jobs,
            "average_wait_time": round(float(avg_wait), 2),
            "average_processing_duration": round(float(avg_proc), 2),
            "retry_count": int(retry_count),
            "failed_jobs": failed_jobs,
            "worker_status": "healthy",
        }

    def get_dashboard_logs(
        self,
        user_id: UUID,
        search: Optional[str] = None,
        event_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[List[ProcessingJobLog], int]:
        query = (
            self.db.query(ProcessingJobLog)
            .join(ProcessingJob, ProcessingJobLog.job_id == ProcessingJob.id)
            .filter(ProcessingJob.user_id == user_id)
        )

        if event_type:
            query = query.filter(ProcessingJobLog.event_type == event_type)

        if search:
            query = query.filter(ProcessingJobLog.message.ilike(f"%{search}%"))

        total = query.count()

        logs = (
            query.order_by(ProcessingJobLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return logs, total

    def get_performance_analytics(self, user_id: UUID, period_days: int = 7) -> dict:
        from app.models import AnalyticsRecord, DocumentText
        from app.document_processing.models import DocumentChunk
        from datetime import timedelta

        def get_avg_metric(metric_name: str) -> float:
            val = (
                self.db.query(func.avg(AnalyticsRecord.metric_value))
                .filter(
                    AnalyticsRecord.user_id == user_id,
                    AnalyticsRecord.metric_name == metric_name
                )
                .scalar()
            )
            return round(float(val), 2) if val else 0.0

        avg_proc = get_avg_metric("total_processing_duration")
        avg_ext = get_avg_metric("extraction_duration")
        avg_clean = get_avg_metric("cleaning_duration")
        avg_chunk = get_avg_metric("chunking_duration")

        total_jobs = self.db.query(func.count(ProcessingJob.id)).filter(ProcessingJob.user_id == user_id).scalar() or 0
        completed = self.db.query(func.count(ProcessingJob.id)).filter(ProcessingJob.user_id == user_id, ProcessingJob.status == JobStatus.COMPLETED).scalar() or 0
        failed = self.db.query(func.count(ProcessingJob.id)).filter(ProcessingJob.user_id == user_id, ProcessingJob.status == JobStatus.FAILED).scalar() or 0

        success_rate = (completed / total_jobs * 100) if total_jobs > 0 else 100.0
        failure_rate = (failed / total_jobs * 100) if total_jobs > 0 else 0.0

        retried_jobs = self.db.query(func.count(ProcessingJob.id)).filter(ProcessingJob.user_id == user_id, ProcessingJob.retry_count > 0).scalar() or 0
        retry_rate = (retried_jobs / total_jobs * 100) if total_jobs > 0 else 0.0

        sizes = (
            self.db.query(func.length(DocumentText.cleaned_text))
            .join(Document, DocumentText.document_id == Document.id)
            .filter(Document.owner_id == user_id, DocumentText.cleaned_text.isnot(None))
            .all()
        )
        sizes_list = [s[0] for s in sizes if s[0] is not None]
        largest = max(sizes_list) if sizes_list else 0
        smallest = min(sizes_list) if sizes_list else 0

        avg_pages = (
            self.db.query(func.avg(DocumentText.page_count))
            .join(Document, DocumentText.document_id == Document.id)
            .filter(Document.owner_id == user_id)
            .scalar() or 0.0
        )

        total_chunks = (
            self.db.query(func.count(DocumentChunk.id))
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(Document.owner_id == user_id)
            .scalar() or 0
        )
        total_docs_with_chunks = (
            self.db.query(func.count(Document.id.distinct()))
            .join(DocumentChunk, Document.id == DocumentChunk.document_id)
            .filter(Document.owner_id == user_id)
            .scalar() or 0
        )
        avg_chunks = float(total_chunks) / float(max(total_docs_with_chunks, 1))

        trends = []
        now = datetime.now(timezone.utc)
        for i in range(period_days - 1, -1, -1):
            day_date = (now - timedelta(days=i)).date()
            day_start = datetime.combine(day_date, datetime.min.time(), tzinfo=timezone.utc)
            day_end = datetime.combine(day_date, datetime.max.time(), tzinfo=timezone.utc)

            day_total = self.db.query(func.count(ProcessingJob.id)).filter(
                ProcessingJob.user_id == user_id,
                ProcessingJob.created_at.between(day_start, day_end)
            ).scalar() or 0

            day_success = self.db.query(func.count(ProcessingJob.id)).filter(
                ProcessingJob.user_id == user_id,
                ProcessingJob.status == JobStatus.COMPLETED,
                ProcessingJob.completed_at.between(day_start, day_end)
            ).scalar() or 0

            day_fail = self.db.query(func.count(ProcessingJob.id)).filter(
                ProcessingJob.user_id == user_id,
                ProcessingJob.status == JobStatus.FAILED,
                ProcessingJob.completed_at.between(day_start, day_end)
            ).scalar() or 0

            day_avg_duration = (
                self.db.query(func.avg(AnalyticsRecord.metric_value))
                .filter(
                    AnalyticsRecord.user_id == user_id,
                    AnalyticsRecord.metric_name == "total_processing_duration",
                    AnalyticsRecord.recorded_at.between(day_start, day_end)
                )
                .scalar() or 0.0
            )

            trends.append({
                "date": day_date.strftime("%Y-%m-%d"),
                "total_jobs": day_total,
                "success_count": day_success,
                "failure_count": day_fail,
                "avg_processing_time": round(float(day_avg_duration), 2),
            })

        return {
            "average_processing_time": round(float(avg_proc), 2),
            "average_extraction_time": round(float(avg_ext), 2),
            "average_cleaning_time": round(float(avg_clean), 2),
            "average_chunking_time": round(float(avg_chunk), 2),
            "success_rate": round(float(success_rate), 2),
            "retry_rate": round(float(retry_rate), 2),
            "failure_rate": round(float(failure_rate), 2),
            "largest_processed_document_size": largest,
            "smallest_processed_document_size": smallest,
            "average_pages_processed": round(float(avg_pages), 2),
            "average_chunks_generated": round(float(avg_chunks), 2),
            "trends": trends,
        }

    def get_job_timeline(self, job_id: UUID, user_id: UUID) -> dict:
        from app.models import Document

        job = self._get_owned_job(job_id, user_id)

        doc = self.db.get(Document, job.document_id)
        doc_title = doc.title if doc else "Unknown Document"
        case_title = doc.case.title if doc and doc.case else None

        logs = (
            self.db.query(ProcessingJobLog)
            .filter(ProcessingJobLog.job_id == job_id)
            .order_by(ProcessingJobLog.created_at.asc())
            .all()
        )

        stages_info = {
            "Queued": {"status": "completed", "timestamp": job.created_at, "duration": 0.0},
            "Extraction": {"status": "pending", "timestamp": None, "duration": 0.0},
            "Cleaning": {"status": "pending", "timestamp": None, "duration": 0.0},
            "Chunking": {"status": "pending", "timestamp": None, "duration": 0.0},
            "Terminal": {"status": "pending", "timestamp": None, "duration": 0.0},
        }

        from app.models import AnalyticsRecord
        records = (
            self.db.query(AnalyticsRecord)
            .filter(
                AnalyticsRecord.user_id == user_id,
                AnalyticsRecord.metadata_json.like(f'%"{job_id}"%') | AnalyticsRecord.metadata_json.like(f'%{str(job_id)}%')
            )
            .all()
        )
        durations = {r.metric_name: r.metric_value for r in records}

        stages_info["Extraction"]["duration"] = durations.get("extraction_duration", 0.0)
        stages_info["Cleaning"]["duration"] = durations.get("cleaning_duration", 0.0)
        stages_info["Chunking"]["duration"] = durations.get("chunking_duration", 0.0)

        for log in logs:
            msg = log.message.lower()
            if "queued" in msg or "created" in msg:
                stages_info["Queued"]["timestamp"] = log.created_at
            if "starting" in msg or "running" in msg or "extraction started" in msg:
                stages_info["Extraction"]["status"] = "running"
                stages_info["Extraction"]["timestamp"] = log.created_at
            if "saving extracted text" in msg or "extracted text saved" in msg:
                stages_info["Extraction"]["status"] = "completed"
            if "cleaning & normalizing" in msg or "cleaning started" in msg:
                stages_info["Cleaning"]["status"] = "running"
                stages_info["Cleaning"]["timestamp"] = log.created_at
            if "saving cleaned text" in msg or "cleaned text saved" in msg:
                stages_info["Cleaning"]["status"] = "completed"
            if "generating chunks" in msg or "chunking started" in msg:
                stages_info["Chunking"]["status"] = "running"
                stages_info["Chunking"]["timestamp"] = log.created_at
            if "saving chunks" in msg or "chunks saved" in msg:
                stages_info["Chunking"]["status"] = "completed"
            if "completed" in msg or "finished" in msg:
                stages_info["Terminal"]["status"] = "completed"
                stages_info["Terminal"]["timestamp"] = log.created_at
            if "failed" in msg:
                stages_info["Terminal"]["status"] = "failed"
                stages_info["Terminal"]["timestamp"] = log.created_at
                stages_info["Terminal"]["error_message"] = log.message

        if job.status == JobStatus.COMPLETED:
            stages_info["Extraction"]["status"] = "completed"
            stages_info["Cleaning"]["status"] = "completed"
            stages_info["Chunking"]["status"] = "completed"
            stages_info["Terminal"]["status"] = "completed"
            stages_info["Terminal"]["timestamp"] = job.completed_at
        elif job.status == JobStatus.FAILED:
            stages_info["Terminal"]["status"] = "failed"
            stages_info["Terminal"]["timestamp"] = job.completed_at or job.updated_at
            for step in ["Chunking", "Cleaning", "Extraction"]:
                if stages_info[step]["status"] == "running":
                    stages_info[step]["status"] = "failed"
                    stages_info[step]["error_message"] = "Job failed during " + step
                    break
        elif job.status == JobStatus.CANCELLED:
            stages_info["Terminal"]["status"] = "cancelled"
            stages_info["Terminal"]["timestamp"] = job.updated_at

        timeline_list = []
        for name in ["Queued", "Extraction", "Cleaning", "Chunking", "Terminal"]:
            st = stages_info[name]
            timeline_list.append({
                "stage": "Completed" if name == "Terminal" and st["status"] == "completed" else ("Failed" if name == "Terminal" and st["status"] == "failed" else name),
                "status": st["status"],
                "timestamp": st["timestamp"],
                "duration": st["duration"] if st["duration"] > 0 else None,
                "error_message": st.get("error_message"),
            })

        return {
            "job_id": job_id,
            "document_title": doc_title,
            "case_title": case_title,
            "timeline": timeline_list,
        }

    def get_job_warnings(self, job_id: UUID, user_id: UUID) -> List[str]:
        from app.models import DocumentText
        job = self._get_owned_job(job_id, user_id)

        warnings = []
        doc_text = self.db.query(DocumentText).filter(DocumentText.document_id == job.document_id).first()
        if doc_text:
            if doc_text.confidence_score and doc_text.confidence_score < 0.70:
                warnings.append(f"Low OCR confidence score detected: {round(doc_text.confidence_score * 100, 1)}%")

            if doc_text.warnings_json:
                try:
                    raw_warnings = json.loads(doc_text.warnings_json)
                    if isinstance(raw_warnings, list):
                        warnings.extend(raw_warnings)
                    elif isinstance(raw_warnings, dict):
                        for k, v in raw_warnings.items():
                            warnings.append(f"{k}: {v}")
                except Exception:
                    pass

        return warnings

    def get_job_metrics(self, job_id: UUID, user_id: UUID) -> dict:
        from app.models import AnalyticsRecord

        self._get_owned_job(job_id, user_id)

        records = (
            self.db.query(AnalyticsRecord)
            .filter(
                AnalyticsRecord.user_id == user_id,
                AnalyticsRecord.metadata_json.like(f'%"{job_id}"%') | AnalyticsRecord.metadata_json.like(f'%{str(job_id)}%')
            )
            .all()
        )
        durations = {r.metric_name: r.metric_value for r in records}

        return {
            "job_id": job_id,
            "queue_wait_time": durations.get("queue_wait_time", 0.0),
            "worker_execution_time": durations.get("worker_execution_time", 0.0),
            "extraction_duration": durations.get("extraction_duration", 0.0),
            "cleaning_duration": durations.get("cleaning_duration", 0.0),
            "chunking_duration": durations.get("chunking_duration", 0.0),
            "database_save_duration": durations.get("database_save_duration", 0.0),
            "total_processing_duration": durations.get("total_processing_duration", 0.0),
        }



# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------

def get_processing_service(
    db: Session,
) -> ProcessingService:
    """
    Create a ProcessingService bound to the request's DB session.
    The queue singleton is shared across all requests.
    """
    return ProcessingService(db=db, queue=processing_queue)
