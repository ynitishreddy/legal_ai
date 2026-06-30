"""
backend/app/schemas/processing_dashboard.py — Pydantic schemas for Phase 5.5.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class ProcessingQueueHealthResponse(BaseModel):
    queue_length: int
    active_workers: int
    waiting_jobs: int
    running_jobs: int
    average_wait_time: float
    average_processing_duration: float
    retry_count: int
    failed_jobs: int
    worker_status: str

    model_config = ConfigDict(from_attributes=True)


class ProcessingLogItem(BaseModel):
    id: UUID
    job_id: UUID
    timestamp: datetime
    event_type: str
    message: str
    metadata: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class ProcessingLogsListResponse(BaseModel):
    items: List[ProcessingLogItem]
    total: int
    page: int
    page_size: int

    model_config = ConfigDict(from_attributes=True)


class PerformanceTrendPoint(BaseModel):
    date: str
    total_jobs: int
    success_count: int
    failure_count: int
    avg_processing_time: float


class ProcessingPerformanceResponse(BaseModel):
    average_processing_time: float
    average_extraction_time: float
    average_cleaning_time: float
    average_chunking_time: float
    success_rate: float
    retry_rate: float
    failure_rate: float
    largest_processed_document_size: int
    smallest_processed_document_size: int
    average_pages_processed: float
    average_chunks_generated: float
    trends: List[PerformanceTrendPoint]

    model_config = ConfigDict(from_attributes=True)


class JobTimelineEvent(BaseModel):
    stage: str
    status: str
    timestamp: Optional[datetime] = None
    duration: Optional[float] = None
    warnings: List[str] = []
    error_message: Optional[str] = None


class JobTimelineResponse(BaseModel):
    job_id: UUID
    document_title: str
    case_title: Optional[str] = None
    timeline: List[JobTimelineEvent]

    model_config = ConfigDict(from_attributes=True)


class JobWarningsResponse(BaseModel):
    job_id: UUID
    warnings: List[str]

    model_config = ConfigDict(from_attributes=True)


class JobMetricsResponse(BaseModel):
    job_id: UUID
    queue_wait_time: float
    worker_execution_time: float
    extraction_duration: float
    cleaning_duration: float
    chunking_duration: float
    database_save_duration: float
    total_processing_duration: float

    model_config = ConfigDict(from_attributes=True)


class ProcessingDashboardStatsResponse(BaseModel):
    total_jobs: int
    queued: int
    running: int
    completed: int
    failed: int
    cancelled: int
    success_rate: float
    average_processing_time: float
    average_queue_time: float

    model_config = ConfigDict(from_attributes=True)
