"""
Unit and integration tests for ProcessingService.

Directly tests the service logic using SQLAlchemy DB Session.
"""

import uuid
import pytest
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    Case,
    Document,
    JobPriority,
    JobStatus,
    JobType,
    ProcessingJob,
    User,
    UserRole,
)
from app.processing.queue import InMemoryProcessingQueue
from app.processing.service import ProcessingService


@pytest.fixture(scope="function")
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def queue() -> InMemoryProcessingQueue:
    return InMemoryProcessingQueue()


@pytest.fixture
def test_user(db_session: Session) -> User:
    user = User(
        email=f"service_test_{uuid.uuid4().hex[:6]}@example.com",
        username=f"service_test_{uuid.uuid4().hex[:6]}",
        hashed_password="hashed_password_placeholder",
        full_name="Service Tester",
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    yield user
    # Cleanup
    db_session.delete(user)
    db_session.commit()


@pytest.fixture
def test_case(db_session: Session, test_user: User) -> Case:
    case = Case(
        title="Test Case",
        owner_id=test_user.id,
    )
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)
    yield case
    # Cleanup
    db_session.delete(case)
    db_session.commit()


@pytest.fixture
def test_document(db_session: Session, test_user: User, test_case: Case) -> Document:
    doc = Document(
        title="Test Doc",
        filename="test.txt",
        file_path="uploads/test.txt",
        owner_id=test_user.id,
        case_id=test_case.id,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    yield doc
    # Cleanup
    db_session.delete(doc)
    db_session.commit()


# ── Create Job ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_create_job_success(db_session: Session, queue: InMemoryProcessingQueue, test_user: User, test_document: Document):
    service = ProcessingService(db=db_session, queue=queue)
    job = await service.create_job(
        user_id=test_user.id,
        document_id=test_document.id,
        job_type="ocr",
        priority="high",
        max_retries=4,
    )

    assert job.id is not None
    assert job.user_id == test_user.id
    assert job.document_id == test_document.id
    assert job.job_type == JobType.OCR
    assert job.priority == JobPriority.HIGH
    assert job.status == JobStatus.QUEUED
    assert job.max_retries == 4

    # Verify queue contains job id
    assert await queue.contains(job.id) is True

    # Cleanup job
    db_session.delete(job)
    db_session.commit()


@pytest.mark.asyncio
async def test_service_create_duplicate_active_job_fails(db_session: Session, queue: InMemoryProcessingQueue, test_user: User, test_document: Document):
    service = ProcessingService(db=db_session, queue=queue)
    job1 = await service.create_job(
        user_id=test_user.id,
        document_id=test_document.id,
        job_type="ocr",
    )

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        await service.create_job(
            user_id=test_user.id,
            document_id=test_document.id,
            job_type="ocr",
        )
    assert excinfo.value.status_code == 409

    # Cleanup
    db_session.delete(job1)
    db_session.commit()


# ── Status Transitions ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_status_transitions(db_session: Session, queue: InMemoryProcessingQueue, test_user: User, test_document: Document):
    service = ProcessingService(db=db_session, queue=queue)
    job = await service.create_job(user_id=test_user.id, document_id=test_document.id, job_type="cleaning")

    # 1. Starting
    job = service.mark_starting(job.id)
    assert job.status == JobStatus.STARTING
    assert job.current_step == "Initializing"

    # 2. Running
    job = service.mark_running(job.id)
    assert job.status == JobStatus.RUNNING
    assert job.started_at is not None
    assert job.current_step == "Processing"

    # 3. Update Progress
    job = service.update_progress(job.id, percentage=45, current_step="Reading metadata")
    assert job.progress_percentage == 45
    assert job.current_step == "Reading metadata"

    # 4. Completed
    job = service.mark_completed(job.id)
    assert job.status == JobStatus.COMPLETED
    assert job.progress_percentage == 100
    assert job.completed_at is not None

    # Cleanup
    db_session.delete(job)
    db_session.commit()


@pytest.mark.asyncio
async def test_service_mark_failed(db_session: Session, queue: InMemoryProcessingQueue, test_user: User, test_document: Document):
    service = ProcessingService(db=db_session, queue=queue)
    job = await service.create_job(user_id=test_user.id, document_id=test_document.id, job_type="summary")

    job = service.mark_failed(job.id, error_message="Something went wrong", error_detail="Full traceback info")
    assert job.status == JobStatus.FAILED
    assert job.error_message == "Something went wrong"
    assert job.error_detail == "Full traceback info"
    assert job.completed_at is not None

    # Cleanup
    db_session.delete(job)
    db_session.commit()


# ── Cancel & Retry ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_cancel_job(db_session: Session, queue: InMemoryProcessingQueue, test_user: User, test_document: Document):
    service = ProcessingService(db=db_session, queue=queue)
    job = await service.create_job(user_id=test_user.id, document_id=test_document.id, job_type="ocr")

    await service.cancel_job(job_id=job.id, user_id=test_user.id)
    assert job.status == JobStatus.CANCELLED
    assert await queue.contains(job.id) is False

    # Cleanup
    db_session.delete(job)
    db_session.commit()


@pytest.mark.asyncio
async def test_service_retry_job(db_session: Session, queue: InMemoryProcessingQueue, test_user: User, test_document: Document):
    service = ProcessingService(db=db_session, queue=queue)
    job = await service.create_job(user_id=test_user.id, document_id=test_document.id, job_type="ocr", max_retries=2)

    # Fail the job first
    service.mark_failed(job.id, "Failure")

    # Retry the job
    job = await service.retry_job(job.id, user_id=test_user.id)
    assert job.status == JobStatus.QUEUED
    assert job.retry_count == 1
    assert job.error_message is None
    assert await queue.contains(job.id) is True

    # Cleanup
    db_session.delete(job)
    db_session.commit()


# ── Queries & Stats ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_queries(db_session: Session, queue: InMemoryProcessingQueue, test_user: User, test_document: Document):
    service = ProcessingService(db=db_session, queue=queue)
    job1 = await service.create_job(user_id=test_user.id, document_id=test_document.id, job_type="ocr")
    job2 = await service.create_job(user_id=test_user.id, document_id=test_document.id, job_type="summary")

    # Active jobs
    active = service.get_active_jobs(user_id=test_user.id)
    assert len(active) == 2

    # Stats
    stats = service.get_stats(user_id=test_user.id)
    assert stats["queued"] == 2
    assert stats["completed"] == 0

    # Cleanup
    db_session.delete(job1)
    db_session.delete(job2)
    db_session.commit()
