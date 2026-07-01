import uuid
import logging
import threading
import time
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
from app.document_processing.models import DocumentChunk
from app.models.embeddings import DocumentEmbedding, EmbeddingJob

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Singleton service wrapper for the text embedding model.
    Handles lazy loading, thread-safe inference, CPU/GPU detection,
    and fallback mechanisms if packages or model weights fail to load.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(EmbeddingService, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self.settings = get_settings()
        self.model_name = self.settings.embedding_model
        self.dimension = self.settings.embedding_dimension
        self.version = self.settings.embedding_model_version
        self._model = None
        self._model_lock = threading.Lock()
        self._initialized = True

    def _get_device(self) -> str:
        if not self.settings.embedding_gpu_enabled:
            return "cpu"
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _load_model(self):
        if self._model is not None:
            return self._model
        
        with self._model_lock:
            if self._model is not None:
                return self._model
            
            device = self._get_device()
            logger.info("EmbeddingService: Loading model %s on %s...", self.model_name, device)
            start_time = time.time()
            try:
                from sentence_transformers import SentenceTransformer
                # In lazy loading, we fetch and load the model on demand
                self._model = SentenceTransformer(self.model_name, device=device)
                duration = time.time() - start_time
                logger.info(
                    "EmbeddingService: Model %s successfully loaded on %s in %.2fs", 
                    self.model_name, device, duration
                )
            except Exception as e:
                logger.warning(
                    "EmbeddingService: Model loading failed for %s (%s). Falling back to mock generator.",
                    self.model_name, str(e)
                )
                self._model = "mock"
        return self._model

    def embed_text(self, text: str) -> List[float]:
        """Generate embedding vector for a single text string."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings in batch, validating dimensions."""
        if not texts:
            return []
        
        model = self._load_model()
        
        try:
            if model == "mock":
                # Generate deterministic mock embeddings based on string contents
                embeddings = []
                for text in texts:
                    import random
                    # Seed based on content to simulate consistent embeddings
                    h = hash(text) & 0xffffffff
                    random.seed(h)
                    embeddings.append([random.uniform(-1, 1) for _ in range(self.dimension)])
                return embeddings

            # Actual sentence-transformers encoding
            with self._model_lock:
                encoded = model.encode(
                    texts, 
                    batch_size=self.settings.embedding_batch_size, 
                    show_progress_bar=False
                )
                # Convert list or np.ndarray to standard Python float list
                result = [arr.tolist() if hasattr(arr, "tolist") else list(arr) for arr in encoded]

                # Validate dimension correctness
                for idx, vector in enumerate(result):
                    if len(vector) != self.dimension:
                        raise ValueError(
                            f"Dimension validation failed: expected {self.dimension}, got {len(vector)}"
                        )
                return result

        except Exception as e:
            logger.error("EmbeddingService: Inference failed: %s", str(e), exc_info=True)
            raise e

    def get_model_info(self) -> Dict[str, Any]:
        """Expose current model configuration without leaking details."""
        return {
            "model_name": self.model_name,
            "dimension": self.dimension,
            "version": self.version,
            "device": self._get_device(),
            "loaded": self._model is not None,
            "is_mock": self._model == "mock"
        }


class DocumentEmbeddingService:
    """
    CRUD and orchestrations service for document embeddings and jobs database state.
    """
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.inference_service = EmbeddingService()

    def _verify_document_owner(self, document_id: UUID, user_id: UUID) -> Document:
        """Verify the document exists and belongs to the user."""
        doc: Optional[Document] = self.db.get(Document, document_id)
        if doc is None or doc.owner_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found or access denied.",
            )
        return doc

    async def create_embedding_job(
        self,
        user_id: UUID,
        document_id: UUID,
        priority: str = "normal",
    ) -> EmbeddingJob:
        """Create and enqueue an embedding job for the document."""
        # Verify ownership
        self._verify_document_owner(document_id, user_id)
        
        # Verify if chunks exist
        chunk_count = self.db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).count()
        if chunk_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document has no chunks. Complete text extraction and chunking first."
            )

        from app.processing.service import get_processing_service
        proc_service = get_processing_service(self.db)

        # Enqueue via ProcessingJob
        proc_job = await proc_service.create_job(
            user_id=user_id,
            document_id=document_id,
            job_type="embeddings",
            priority=priority,
            max_retries=self.settings.embedding_max_retries,
        )

        # Create/sync corresponding EmbeddingJob in embedding_jobs table
        emb_job = self.db.get(EmbeddingJob, proc_job.id)
        if not emb_job:
            emb_job = EmbeddingJob(
                id=proc_job.id,
                document_id=document_id,
                status=JobStatus.PENDING,
                progress=0,
                retry_count=0,
            )
            self.db.add(emb_job)
            self.db.commit()
            self.db.refresh(emb_job)

        return emb_job

    def get_embedding_status(self, document_id: UUID, user_id: UUID) -> Dict[str, Any]:
        """Fetch real-time document embedding stats and job status."""
        self._verify_document_owner(document_id, user_id)

        # Retrieve latest embedding job
        latest_job = (
            self.db.query(EmbeddingJob)
            .filter(EmbeddingJob.document_id == document_id)
            .order_by(EmbeddingJob.started_at.desc().nullslast(), EmbeddingJob.id.desc())
            .first()
        )

        total_chunks = (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .count()
        )
        embedded_chunks = (
            self.db.query(DocumentEmbedding)
            .filter(DocumentEmbedding.document_id == document_id)
            .count()
        )

        # Determine status enum
        if latest_job:
            job_status = latest_job.status.value if hasattr(latest_job.status, "value") else str(latest_job.status)
        else:
            job_status = "never_embedded" if embedded_chunks == 0 else "completed"

        # If completed, double check all chunks are embedded
        if job_status == "completed" and embedded_chunks < total_chunks:
            # Maybe partially processed?
            job_status = "pending"

        # Load embedding details if available
        first_emb = (
            self.db.query(DocumentEmbedding)
            .filter(DocumentEmbedding.document_id == document_id)
            .first()
        )

        return {
            "document_id": document_id,
            "status": job_status,
            "job_id": latest_job.id if latest_job else None,
            "progress": latest_job.progress if latest_job else (100 if embedded_chunks > 0 else 0),
            "error_message": latest_job.error_message if latest_job else None,
            "embedding_model": first_emb.embedding_model if first_emb else self.settings.embedding_model,
            "embedding_version": first_emb.embedding_version if first_emb else self.settings.embedding_model_version,
            "embedding_dimension": first_emb.embedding_dimension if first_emb else self.settings.embedding_dimension,
            "total_chunks": total_chunks,
            "embedded_chunks": embedded_chunks,
            "updated_at": latest_job.completed_at if latest_job and latest_job.completed_at else (first_emb.updated_at if first_emb else None),
        }

    def list_embedding_jobs(
        self,
        user_id: UUID,
        status_filter: Optional[str] = None,
        document_id: Optional[UUID] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[EmbeddingJob], int]:
        """Retrieve paginated embedding jobs."""
        q = self.db.query(EmbeddingJob).join(Document).filter(Document.owner_id == user_id)

        if status_filter:
            q = q.filter(EmbeddingJob.status == JobStatus(status_filter))
        if document_id:
            q = q.filter(EmbeddingJob.document_id == document_id)

        total = q.count()
        jobs = (
            q.order_by(EmbeddingJob.started_at.desc().nullslast(), EmbeddingJob.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return jobs, total

    def get_embedding_job(self, job_id: UUID, user_id: UUID) -> EmbeddingJob:
        """Fetch a specific embedding job with owner checking."""
        job: Optional[EmbeddingJob] = self.db.query(EmbeddingJob).join(Document).filter(
            EmbeddingJob.id == job_id, Document.owner_id == user_id
        ).first()
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Embedding job not found"
            )
        return job

    async def retry_embedding_job(self, job_id: UUID, user_id: UUID) -> EmbeddingJob:
        """Retry a failed embedding job."""
        job = self.get_embedding_job(job_id, user_id)
        if job.status != JobStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only failed embedding jobs can be retried."
            )

        from app.processing.service import get_processing_service
        proc_service = get_processing_service(self.db)
        await proc_service.retry_job(job_id=job_id, user_id=user_id)

        # Sync changes
        self.db.refresh(job)
        return job

    async def cancel_or_delete_embedding_job(self, job_id: UUID, user_id: UUID) -> None:
        """Cancel an active job or delete a finished job."""
        # Check if job is linked to a ProcessingJob
        proc_job: Optional[ProcessingJob] = self.db.get(ProcessingJob, job_id)
        if proc_job:
            # Check owner
            if proc_job.user_id != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            
            # Cancel if active
            from app.processing.service import _ACTIVE_STATUSES
            if proc_job.status in _ACTIVE_STATUSES:
                from app.processing.service import get_processing_service
                proc_service = get_processing_service(self.db)
                await proc_service.cancel_job(job_id=job_id, user_id=user_id)
        
        # Delete job records from DB
        self.db.query(EmbeddingJob).filter(EmbeddingJob.id == job_id).delete()
        if proc_job:
            self.db.delete(proc_job)
        self.db.commit()

    def get_statistics(self, user_id: UUID) -> Dict[str, Any]:
        """Aggregate stats for the user's embedding dashboard."""
        # Embedded documents count
        total_docs = (
            self.db.query(func.count(func.distinct(DocumentEmbedding.document_id)))
            .join(Document, Document.id == DocumentEmbedding.document_id)
            .filter(Document.owner_id == user_id)
            .scalar() or 0
        )

        # Embedded chunks count
        total_chunks = (
            self.db.query(func.count(DocumentEmbedding.id))
            .join(Document, Document.id == DocumentEmbedding.document_id)
            .filter(Document.owner_id == user_id)
            .scalar() or 0
        )

        # Failed embedding jobs
        failed_jobs = (
            self.db.query(func.count(EmbeddingJob.id))
            .join(Document, Document.id == EmbeddingJob.document_id)
            .filter(Document.owner_id == user_id, EmbeddingJob.status == JobStatus.FAILED)
            .scalar() or 0
        )

        # Active embedding jobs
        active_jobs = (
            self.db.query(func.count(EmbeddingJob.id))
            .join(Document, Document.id == EmbeddingJob.document_id)
            .filter(
                Document.owner_id == user_id, 
                EmbeddingJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED, JobStatus.STARTING, JobStatus.RUNNING])
            )
            .scalar() or 0
        )

        # Queue size (waiting in queue)
        queue_size = (
            self.db.query(func.count(EmbeddingJob.id))
            .join(Document, Document.id == EmbeddingJob.document_id)
            .filter(Document.owner_id == user_id, EmbeddingJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED]))
            .scalar() or 0
        )

        # Retry count sum
        retry_sum = (
            self.db.query(func.sum(EmbeddingJob.retry_count))
            .join(Document, Document.id == EmbeddingJob.document_id)
            .filter(Document.owner_id == user_id)
            .scalar() or 0
        )

        # Average completed embedding job time (seconds)
        avg_time = (
            self.db.query(
                func.avg(
                    func.extract("epoch", EmbeddingJob.completed_at)
                    - func.extract("epoch", EmbeddingJob.started_at)
                )
            )
            .join(Document, Document.id == EmbeddingJob.document_id)
            .filter(
                Document.owner_id == user_id,
                EmbeddingJob.status == JobStatus.COMPLETED,
                EmbeddingJob.started_at.isnot(None),
                EmbeddingJob.completed_at.isnot(None),
            )
            .scalar()
        )

        # Throughput: chunks embedded / duration
        # We can look up all completed jobs, query the total chunks and average time
        throughput = None
        if avg_time and float(avg_time) > 0:
            # Retrieve total chunks embedded in completed jobs
            completed_job_ids = (
                self.db.query(EmbeddingJob.id)
                .join(Document, Document.id == EmbeddingJob.document_id)
                .filter(Document.owner_id == user_id, EmbeddingJob.status == JobStatus.COMPLETED)
                .all()
            )
            completed_job_uuids = [r[0] for r in completed_job_ids]
            if completed_job_uuids:
                # Find total chunk counts associated with these documents
                completed_docs = (
                    self.db.query(EmbeddingJob.document_id)
                    .filter(EmbeddingJob.id.in_(completed_job_uuids))
                    .distinct()
                    .all()
                )
                completed_doc_uuids = [r[0] for r in completed_docs]
                
                total_chunks_embedded = (
                    self.db.query(func.count(DocumentEmbedding.id))
                    .filter(DocumentEmbedding.document_id.in_(completed_doc_uuids))
                    .scalar() or 0
                )
                
                total_duration = (
                    self.db.query(
                        func.sum(
                            func.extract("epoch", EmbeddingJob.completed_at)
                            - func.extract("epoch", EmbeddingJob.started_at)
                        )
                    )
                    .filter(EmbeddingJob.id.in_(completed_job_uuids))
                    .scalar() or 0.0
                )
                
                if total_duration > 0:
                    throughput = float(total_chunks_embedded) / float(total_duration)

        return {
            "total_embedded_documents": total_docs,
            "total_embedded_chunks": total_chunks,
            "average_embedding_time_seconds": round(float(avg_time), 2) if avg_time else None,
            "embedding_queue_size": queue_size,
            "failed_embeddings": failed_jobs,
            "active_embeddings": active_jobs,
            "retry_count": int(retry_sum),
            "average_batch_size": self.settings.embedding_batch_size,
            "processing_throughput_chunks_per_sec": round(throughput, 2) if throughput is not None else None,
        }


def sync_embedding_job_status(db: Session, proc_job: ProcessingJob) -> None:
    """Helper to keep EmbeddingJob schema synchronized with active ProcessingJob lifecycle."""
    if proc_job.job_type != JobType.EMBEDDINGS:
        return
    emb_job = db.get(EmbeddingJob, proc_job.id)
    if not emb_job:
        # Create on the fly if needed
        emb_job = EmbeddingJob(
            id=proc_job.id,
            document_id=proc_job.document_id,
            status=proc_job.status,
            progress=proc_job.progress_percentage,
            retry_count=proc_job.retry_count,
        )
        db.add(emb_job)
    else:
        emb_job.status = proc_job.status
        emb_job.progress = proc_job.progress_percentage
        emb_job.retry_count = proc_job.retry_count
        emb_job.error_message = proc_job.error_message

        # Sync timestamps
        if proc_job.status == JobStatus.RUNNING:
            if not emb_job.started_at:
                emb_job.started_at = proc_job.started_at or datetime.now(timezone.utc)
        elif proc_job.status == JobStatus.COMPLETED:
            emb_job.completed_at = proc_job.completed_at or datetime.now(timezone.utc)
        elif proc_job.status == JobStatus.FAILED:
            emb_job.failed_at = proc_job.completed_at or datetime.now(timezone.utc)
            emb_job.error_message = proc_job.error_message
        elif proc_job.status == JobStatus.CANCELLED:
            emb_job.completed_at = proc_job.completed_at or datetime.now(timezone.utc)

    db.commit()
