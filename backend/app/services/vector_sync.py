import logging
import time
import math
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Document,
    JobStatus,
    ProcessingJob,
    JobType,
    JobPriority,
    JobLogEventType,
)
from app.models.embeddings import DocumentEmbedding, VectorSyncJob
from app.document_processing.models import DocumentChunk
from app.services.qdrant import QdrantService
from app.processing.queue import AbstractProcessingQueue, processing_queue

logger = logging.getLogger(__name__)


class VectorSyncService:
    """
    Orchestration service for synchronizing document vector embeddings
    from PostgreSQL to the Qdrant vector database.
    """

    def __init__(self, db: Session, queue: Optional[AbstractProcessingQueue] = None) -> None:
        self.db = db
        self.queue = queue or processing_queue
        self.qdrant_svc = QdrantService()
        self.settings = get_settings()

    async def create_sync_job(
        self,
        user_id: UUID,
        document_id: UUID,
        priority: str = "normal",
    ) -> VectorSyncJob:
        """
        Creates a synchronization job in PostgreSQL and enqueues a corresponding
        ProcessingJob for the background worker.
        """
        # Ensure document exists
        doc = self.db.get(Document, document_id)
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {document_id} not found.",
            )

        # Check for active sync job first to avoid duplicates
        existing_job = (
            self.db.query(VectorSyncJob)
            .filter(
                and_(
                    VectorSyncJob.document_id == document_id,
                    VectorSyncJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED, JobStatus.STARTING, JobStatus.RUNNING]),
                )
            )
            .first()
        )
        if existing_job:
            logger.info("VectorSyncService: Active job already exists for document %s - returning existing", document_id)
            return existing_job

        # 1. Create matching ProcessingJob
        proc_priority = JobPriority.NORMAL
        if priority == "high":
            proc_priority = JobPriority.HIGH
        elif priority == "urgent":
            proc_priority = JobPriority.URGENT
        elif priority == "low":
            proc_priority = JobPriority.LOW

        proc_job = ProcessingJob(
            user_id=user_id,
            document_id=document_id,
            case_id=doc.case_id,
            job_type=JobType.VECTOR_SYNC,
            status=JobStatus.QUEUED,
            priority=proc_priority,
            progress_percentage=0,
            current_step="Pending Queue Ingestion",
        )
        self.db.add(proc_job)
        self.db.commit()
        self.db.refresh(proc_job)

        # 2. Create the VectorSyncJob matching the ProcessingJob UUID
        sync_job = VectorSyncJob(
            id=proc_job.id,  # Sync ID to make tracking easier
            document_id=document_id,
            status=JobStatus.PENDING,
            progress=0,
        )
        self.db.add(sync_job)
        
        # Write Processing Log
        from app.models import ProcessingJobLog
        log = ProcessingJobLog(
            job_id=proc_job.id,
            event_type=JobLogEventType.CREATED,
            message="Vector database synchronization job initialized.",
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(sync_job)

        # 3. Enqueue to Processing Queue
        await self.queue.enqueue(proc_job.id)
        logger.info(
            "VectorSyncService: Created and enqueued vector sync job=%s for document=%s",
            sync_job.id, document_id
        )
        
        return sync_job

    def sync_vector_sync_job_status(
        self,
        job_id: UUID,
        status: JobStatus,
        progress: int,
        error_message: Optional[str] = None,
    ) -> None:
        """Synchronizes VectorSyncJob with background ProcessingJob state updates."""
        sync_job = self.db.get(VectorSyncJob, job_id)
        if not sync_job:
            return

        sync_job.status = status
        sync_job.progress = progress

        now = datetime.now(timezone.utc)
        if status in (JobStatus.STARTING, JobStatus.RUNNING):
            if not sync_job.started_at:
                sync_job.started_at = now
        elif status == JobStatus.COMPLETED:
            sync_job.completed_at = now
        elif status == JobStatus.FAILED:
            sync_job.failed_at = now
            sync_job.error_message = error_message
        elif status == JobStatus.CANCELLED:
            sync_job.failed_at = now
            sync_job.error_message = "Synchronization cancelled by administrative request."

        self.db.commit()

    async def sync_document_vectors(
        self,
        job_id: UUID,
        document_id: UUID,
        progress_callback = None,
    ) -> bool:
        """
        Ingests document chunk embeddings from PostgreSQL to Qdrant.
        Operates in configurable batches, enriches metadata payloads,
        and marks records as is_synced on success.
        """
        doc = self.db.get(Document, document_id)
        if not doc:
            raise ValueError(f"Document {document_id} not found.")

        # Query all database embeddings for this document
        embeddings = (
            self.db.query(DocumentEmbedding)
            .filter(DocumentEmbedding.document_id == document_id)
            .all()
        )
        if not embeddings:
            logger.warning("VectorSyncService: No embeddings found in Postgres for document %s. Skipping sync.", document_id)
            return True

        # Query chunks to build rich payload
        chunks = (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .all()
        )
        chunk_map = {c.id: c for c in chunks}

        total_vectors = len(embeddings)
        logger.info("VectorSyncService: Syncing %d vectors for document %s to Qdrant...", total_vectors, document_id)

        batch_size = self.settings.qdrant_upload_batch_size
        points_to_upsert = []

        start_time = time.time()
        for idx, emb in enumerate(embeddings):
            chunk = chunk_map.get(emb.chunk_id)
            
            # Form metadata payload
            payload = {
                "document_id": str(document_id),
                "chunk_id": str(emb.chunk_id),
                "case_id": str(doc.case_id) if doc.case_id else "",
                "owner_id": str(doc.owner_id) if doc.owner_id else "",
                "filename": doc.filename,
                "page_number": chunk.page_start if chunk else 1,
                "section_title": chunk.section_name if (chunk and chunk.section_name) else "",
                "chunk_index": chunk.chunk_index if chunk else 0,
                "document_type": doc.document_type if hasattr(doc, "document_type") else "txt",
                "tags": doc.user_tags if (hasattr(doc, "user_tags") and doc.user_tags) else [],
                "created_at": doc.created_at.isoformat() if doc.created_at else datetime.now(timezone.utc).isoformat(),
                "embedding_version": emb.embedding_version,
            }

            points_to_upsert.append({
                "id": emb.id,
                "vector": emb.embedding_vector,
                "payload": payload,
            })

            # Upload batch when limit is reached, or at end
            if len(points_to_upsert) >= batch_size or idx == total_vectors - 1:
                # Perform upsert
                self.qdrant_svc.upsert_vectors(points_to_upsert)
                
                # Mark these embeddings as synced in PostgreSQL
                synced_ids = [p["id"] for p in points_to_upsert]
                self.db.query(DocumentEmbedding).filter(DocumentEmbedding.id.in_(synced_ids)).update(
                    {DocumentEmbedding.is_synced: True, DocumentEmbedding.synced_at: datetime.now(timezone.utc)},
                    synchronize_session=False,
                )
                self.db.commit()

                # Call progress callback if registered
                if progress_callback:
                    progress_percent = int(((idx + 1) / total_vectors) * 100)
                    progress_callback(progress_percent)

                points_to_upsert = []

        duration = time.time() - start_time
        logger.info("VectorSyncService: Successfully synced %d vectors for document %s in %.2fs", total_vectors, document_id, duration)
        return True

    def delete_document_vectors(self, document_id: UUID) -> bool:
        """Deletes Qdrant vectors and resets synced state in PostgreSQL."""
        try:
            # 1. Delete Qdrant vectors
            self.qdrant_svc.delete_by_document(document_id)
            
            # 2. Reset postgres synced status
            self.db.query(DocumentEmbedding).filter(DocumentEmbedding.document_id == document_id).update(
                {DocumentEmbedding.is_synced: False, DocumentEmbedding.synced_at: None},
                synchronize_session=False,
            )
            self.db.commit()
            return True
        except Exception as e:
            logger.error("VectorSyncService: Deleting vectors failed for document %s: %s", document_id, str(e))
            return False

    def get_statistics(self) -> Dict[str, Any]:
        """Generate vector synchronization metrics."""
        total_vectors = self.db.query(func.count(DocumentEmbedding.id)).scalar() or 0
        synced_vectors = self.db.query(func.count(DocumentEmbedding.id)).filter(DocumentEmbedding.is_synced == True).scalar() or 0
        pending_vectors = total_vectors - synced_vectors

        # Queue sizes
        embedding_queue = self.db.query(func.count(ProcessingJob.id)).filter(
            and_(ProcessingJob.job_type == JobType.EMBEDDINGS, ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        ).scalar() or 0
        sync_queue = self.db.query(func.count(ProcessingJob.id)).filter(
            and_(ProcessingJob.job_type == JobType.VECTOR_SYNC, ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        ).scalar() or 0
        
        # Failed jobs count
        failed_sync = self.db.query(func.count(VectorSyncJob.id)).filter(VectorSyncJob.status == JobStatus.FAILED).scalar() or 0

        # Collection info
        col_info = self.qdrant_svc.get_collection_info()

        return {
            "total_vectors": total_vectors,
            "synced_vectors": synced_vectors,
            "pending_vectors": pending_vectors,
            "failed_vectors": failed_sync,
            "embedding_queue_size": embedding_queue,
            "sync_queue_size": sync_queue,
            "collection_name": col_info["name"],
            "collection_status": col_info["status"],
            "collection_dimension": col_info["dimension"],
            "qdrant_vectors_count": col_info["vectors_count"],
        }

    def get_sync_status(self, document_id: UUID) -> Dict[str, Any]:
        """Status report for a single document."""
        total_chunks = self.db.query(func.count(DocumentChunk.id)).filter(DocumentChunk.document_id == document_id).scalar() or 0
        total_embeddings = self.db.query(func.count(DocumentEmbedding.id)).filter(DocumentEmbedding.document_id == document_id).scalar() or 0
        synced_embeddings = self.db.query(func.count(DocumentEmbedding.id)).filter(
            and_(DocumentEmbedding.document_id == document_id, DocumentEmbedding.is_synced == True)
        ).scalar() or 0

        # Check for active/completed jobs
        job = (
            self.db.query(VectorSyncJob)
            .filter(VectorSyncJob.document_id == document_id)
            .order_by(VectorSyncJob.started_at.desc().nulls_last())
            .first()
        )

        status = "never_synced"
        progress = 0
        error_message = None
        job_id = None

        if job:
            job_id = job.id
            progress = job.progress
            error_message = job.error_message
            if job.status == JobStatus.COMPLETED:
                status = "completed"
            elif job.status == JobStatus.FAILED:
                status = "failed"
            elif job.status == JobStatus.CANCELLED:
                status = "cancelled"
            elif job.status in (JobStatus.PENDING, JobStatus.QUEUED):
                status = "pending"
            elif job.status in (JobStatus.STARTING, JobStatus.RUNNING):
                status = "running"
        elif total_embeddings > 0 and synced_embeddings == total_embeddings:
            status = "completed"
        elif total_embeddings > 0 and synced_embeddings < total_embeddings:
            status = "failed"

        return {
            "document_id": str(document_id),
            "status": status,
            "job_id": str(job_id) if job_id else None,
            "progress": progress,
            "error_message": error_message,
            "total_chunks": total_chunks,
            "embeddings_count": total_embeddings,
            "synced_count": synced_embeddings,
            "updated_at": job.completed_at.isoformat() if (job and job.completed_at) else None,
        }

    async def retry_sync_job(self, job_id: UUID) -> VectorSyncJob:
        """Retry a failed sync job by re-enqueueing it."""
        job = self.db.get(VectorSyncJob, job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Sync job {job_id} not found."
            )

        proc_job = self.db.get(ProcessingJob, job_id)
        if not proc_job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Processing job {job_id} not found."
            )

        # Reset states
        job.status = JobStatus.PENDING
        job.progress = 0
        job.retry_count += 1
        job.failed_at = None
        job.error_message = None

        proc_job.status = JobStatus.QUEUED
        proc_job.progress_percentage = 0
        proc_job.error_message = None
        proc_job.retry_count += 1

        self.db.commit()

        # Re-enqueue
        await self.queue.enqueue(job_id)
        logger.info("VectorSyncService: Re-enqueued retry for sync job=%s", job_id)
        return job

    async def sync_all_pending(self, user_id: UUID) -> int:
        """Finds all documents with unsynced embeddings and spawns jobs for them."""
        # Find document IDs with at least one unsynced embedding
        unsynced_doc_ids = (
            self.db.query(DocumentEmbedding.document_id)
            .filter(DocumentEmbedding.is_synced == False)
            .distinct()
            .all()
        )
        unsynced_doc_ids = [row[0] for row in unsynced_doc_ids]

        job_count = 0
        for doc_id in unsynced_doc_ids:
            try:
                await self.create_sync_job(user_id=user_id, document_id=doc_id)
                job_count += 1
            except Exception as e:
                logger.error("VectorSyncService: Failed to trigger automatic sync job for doc %s: %s", doc_id, str(e))
        
        return job_count

    async def force_resync_all(self, user_id: UUID) -> int:
        """Resets is_synced flags for all documents and enqueues sync jobs for them."""
        # Reset all embeddings status
        self.db.query(DocumentEmbedding).update(
            {DocumentEmbedding.is_synced: False, DocumentEmbedding.synced_at: None},
            synchronize_session=False,
        )
        self.db.commit()

        # Get all document IDs that have any embeddings
        doc_ids = (
            self.db.query(DocumentEmbedding.document_id)
            .distinct()
            .all()
        )
        doc_ids = [row[0] for row in doc_ids]

        job_count = 0
        for doc_id in doc_ids:
            try:
                await self.create_sync_job(user_id=user_id, document_id=doc_id)
                job_count += 1
            except Exception as e:
                logger.error("VectorSyncService: Failed to force sync doc %s: %s", doc_id, str(e))

        return job_count
