"""
app.processing.worker — Background processing worker.

Implements a lightweight asyncio polling loop that:
  1. Dequeues job IDs from the queue
  2. Simulates multi-step work with progress updates
  3. Marks jobs as COMPLETED or FAILED
  4. Auto-retries if retry_count < max_retries

The worker is started in FastAPI's lifespan and stopped on shutdown.
It is fully replaceable by a Celery worker in a future phase — only
the inner _process_job() method needs to be adapted.
"""

import asyncio
import json
import logging
import time
import traceback
from contextlib import asynccontextmanager
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import JobStatus, ProcessingJob
from app.processing.queue import AbstractProcessingQueue, processing_queue
from app.processing.service import ProcessingService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simulated processing steps
# ---------------------------------------------------------------------------

# Each step: (progress_percentage, step_name, sleep_seconds)
_PROCESSING_STEPS = [
    (5,   "Preparing",    0.5),
    (15,  "Initializing", 0.5),
    (30,  "Loading",      1.0),
    (50,  "Processing",   1.5),
    (70,  "Analyzing",    1.0),
    (85,  "Finalizing",   0.5),
    (95,  "Validating",   0.5),
    (100, "Completed",    0.2),
]
def save_performance_metrics(
    db: Session,
    job: ProcessingJob,
    queue_wait_time: float,
    worker_execution_time: float,
    extraction_duration: float,
    cleaning_duration: float,
    chunking_duration: float,
    db_save_duration: float,
):
    from app.models import AnalyticsRecord
    metrics = {
        "queue_wait_time": queue_wait_time,
        "worker_execution_time": worker_execution_time,
        "extraction_duration": extraction_duration,
        "cleaning_duration": cleaning_duration,
        "chunking_duration": chunking_duration,
        "database_save_duration": db_save_duration,
        "total_processing_duration": queue_wait_time + worker_execution_time,
    }
    for key, val in metrics.items():
        record = AnalyticsRecord(
            metric_name=key,
            metric_value=float(val),
            metric_unit="seconds",
            category="document_processing",
            user_id=job.user_id,
            case_id=job.case_id,
            metadata_json=json.dumps({
                "job_id": str(job.id),
                "document_id": str(job.document_id),
                "job_type": job.job_type.value,
            })
        )
        db.add(record)
    db.commit()

class ProcessingWorker:
    """
    Asyncio-based background worker for processing jobs.

    Usage:
        worker = ProcessingWorker()
        await worker.start()   # in lifespan startup
        await worker.stop()    # in lifespan shutdown
    """

    def __init__(
        self,
        queue: AbstractProcessingQueue = processing_queue,
        poll_interval: float = 2.0,
    ) -> None:
        self._queue = queue
        self._poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None
        self._running = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            logger.warning("ProcessingWorker already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="processing_worker")
        logger.info("ProcessingWorker started (poll_interval=%.1fs)", self._poll_interval)

    async def stop(self) -> None:
        """Signal the worker to stop and await termination."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ProcessingWorker stopped")

    # ── Polling loop ──────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Main loop: dequeue → process → repeat."""
        logger.debug("ProcessingWorker._poll_loop: entering loop")
        while self._running:
            try:
                job_id: Optional[UUID] = await self._queue.dequeue()
                if job_id is not None:
                    await self._handle_job(job_id)
                else:
                    await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("ProcessingWorker._poll_loop: unhandled error: %s", exc, exc_info=True)
                await asyncio.sleep(self._poll_interval)

    async def _handle_job(self, job_id: UUID) -> None:
        """
        Process a single job safely.

        Opens its own DB session to avoid sharing sessions across async boundaries.
        """
        db: Session = SessionLocal()
        try:
            service = ProcessingService(db=db, queue=self._queue)
            job: Optional[ProcessingJob] = db.get(ProcessingJob, job_id)

            if job is None:
                logger.warning("ProcessingWorker: job=%s not found — skipping", job_id)
                return

            if job.status == JobStatus.CANCELLED:
                logger.info("ProcessingWorker: job=%s was cancelled — skipping", job_id)
                return

            logger.info(
                "ProcessingWorker: starting job=%s type=%s doc=%s",
                job.id, job.job_type.value, job.document_id,
            )
            await self._process_job(service, job)

        except Exception as exc:  # pylint: disable=broad-except
            logger.error(
                "ProcessingWorker._handle_job: unhandled exception for job=%s: %s",
                job_id, exc, exc_info=True,
            )
            # Try to mark failed — best-effort
            try:
                service.mark_failed(
                    job_id=job_id,
                    error_message=str(exc),
                    error_detail=traceback.format_exc(),
                )
            except Exception:  # pylint: disable=broad-except
                pass
        finally:
            db.close()

    async def _process_job(self, service: ProcessingService, job: ProcessingJob) -> None:
        """
        Run the actual document processing and text extraction pipeline.
        Executes CPU-bound file parsing inside the default loop executor
        to keep the FastAPI application responsive.
        """
        job_id = job.id
        db = service.db

        from app.models import JobType
        if job.job_type == JobType.EMBEDDINGS:
            await self._run_embedding_pipeline(service, job)
            return
        if job.job_type == JobType.VECTOR_SYNC:
            await self._run_vector_sync_pipeline(service, job)
            return
        if job.job_type == JobType.TIMELINE:
            await self._run_timeline_pipeline(service, job)
            return


        worker_execution_start_time = time.time()
        created_timestamp = job.created_at.timestamp()
        queue_wait_time = max(0.0, worker_execution_start_time - created_timestamp)

        try:
            # 1. Transition PENDING/QUEUED → STARTING
            service.mark_starting(job_id)
            await asyncio.sleep(0.1)

            # 2. Transition STARTING → RUNNING
            service.mark_running(job_id)

            # 3. Retrieve core Document details
            from app.models import Document
            doc = db.get(Document, job.document_id)
            if not doc:
                raise ValueError(f"Associated document record {job.document_id} not found")

            # 4. Progress updates & callbacks
            service.update_progress(job_id, percentage=10, current_step="Detecting File Type")

            def progress_callback(page_num: int, total_pages: int):
                # Scale progress from 25% to 90% based on active OCR progress
                percentage = 25 + int((page_num / total_pages) * 65)
                service.update_progress(
                    job_id=job_id,
                    percentage=percentage,
                    current_step=f"Running OCR (Page {page_num} of {total_pages})",
                )

            service.update_progress(job_id, percentage=20, current_step="Extracting Text")

            # 5. Run the synchronous text extraction in executor thread pool to avoid blocking async loop
            from app.document_processing.pipeline import document_processing_pipeline
            loop = asyncio.get_running_loop()
            
            extraction_start_time = time.time()
            result = await loop.run_in_executor(
                None,
                document_processing_pipeline.process_document,
                doc.file_path,
                doc.mime_type,
                progress_callback,
            )
            extraction_duration = result.processing_time if result.processing_time else (time.time() - extraction_start_time)

            # 6. Save extracted text
            service.update_progress(job_id, percentage=90, current_step="Saving Extracted Text")
            from app.document_processing.service import DocumentProcessingService
            doc_text_service = DocumentProcessingService(db)
            
            save_extraction_start = time.time()
            doc_text_service.save_extraction_result(job.document_id, result)
            save_extraction_duration = time.time() - save_extraction_start

            # 7. Clean and normalize extracted text (Phase 5.3)
            service.update_progress(job_id, percentage=93, current_step="Cleaning & Normalizing")
            from app.document_processing.cleaning.pipeline import DocumentTextCleaningPipeline
            cleaning_pipeline = DocumentTextCleaningPipeline()

            start_cleaning_time = time.time()
            doc_category_str = doc.document_category.value if hasattr(doc.document_category, "value") else str(doc.document_category)

            cleaned_text, cleaning_report = await loop.run_in_executor(
                None,
                cleaning_pipeline.clean_text,
                result.extracted_text,
                doc_category_str,
            )
            cleaning_duration = time.time() - start_cleaning_time

            # 8. Save cleaned text
            service.update_progress(job_id, percentage=94, current_step="Saving Cleaned Text")
            
            save_cleaning_start = time.time()
            doc_text_service.save_cleaning_result(
                document_id=job.document_id,
                cleaned_text=cleaned_text,
                report=cleaning_report,
                processing_time=cleaning_duration,
            )
            save_cleaning_duration = time.time() - save_cleaning_start

            # 9. Generate and persist chunks (Phase 5.4)
            service.update_progress(job_id, percentage=96, current_step="Generating Chunks")
            from app.document_processing.chunking.pipeline import document_chunking_pipeline
            from app.document_processing.chunking.service import DocumentChunkingService

            chunking_start_time = time.time()
            chunks, chunk_report, strategy_name = await loop.run_in_executor(
                None,
                document_chunking_pipeline.generate_chunks,
                cleaned_text,
                doc_category_str,
            )
            chunking_duration = time.time() - chunking_start_time

            service.update_progress(job_id, percentage=98, current_step="Saving Chunks")
            chunking_service = DocumentChunkingService(db)
            
            save_chunking_start = time.time()
            chunking_service.persist_chunks(
                document_id=job.document_id,
                chunks=chunks,
                strategy_name=strategy_name,
                report=chunk_report,
            )
            save_chunking_duration = time.time() - save_chunking_start

            # 10. Complete job
            service.mark_completed(job_id)

            # Auto-trigger embedding job after chunking completes
            try:
                logger.info("ProcessingWorker: Auto-triggering embedding job for document %s", job.document_id)
                from app.services.embeddings import DocumentEmbeddingService
                emb_db_svc = DocumentEmbeddingService(db)
                await emb_db_svc.create_embedding_job(
                    user_id=job.user_id,
                    document_id=job.document_id,
                    priority=job.priority.value if hasattr(job.priority, "value") else str(job.priority),
                )
            except Exception as e:
                logger.error("ProcessingWorker: Failed to auto-trigger embedding job for document %s: %s", job.document_id, str(e))

            
            worker_execution_time = time.time() - worker_execution_start_time
            db_save_duration = save_extraction_duration + save_cleaning_duration + save_chunking_duration

            # Persist Analytics performance metrics
            save_performance_metrics(
                db=db,
                job=job,
                queue_wait_time=queue_wait_time,
                worker_execution_time=worker_execution_time,
                extraction_duration=extraction_duration,
                cleaning_duration=cleaning_duration,
                chunking_duration=chunking_duration,
                db_save_duration=db_save_duration,
            )

            logger.info(
                "ProcessingWorker: Completed text extraction, cleaning & chunking for job=%s doc=%s method=%s",
                job_id,
                job.document_id,
                result.extraction_method,
            )



        except Exception as exc:

            logger.error("ProcessingWorker: Job=%s failed with exception: %s", job_id, exc, exc_info=True)
            # Bubble up to handle automatic retry logic in caller
            raise exc

    async def _run_embedding_pipeline(self, service: ProcessingService, job: ProcessingJob) -> None:
        """Runs embedding inference in batches and persists the vectors."""
        import math
        job_id = job.id
        db = service.db
        worker_execution_start_time = time.time()
        created_timestamp = job.created_at.timestamp()
        queue_wait_time = max(0.0, worker_execution_start_time - created_timestamp)

        try:
            # 1. Transition PENDING/QUEUED → STARTING
            service.mark_starting(job_id)
            await asyncio.sleep(0.1)

            # 2. Transition STARTING → RUNNING
            service.mark_running(job_id)

            # 3. Retrieve chunks to embed
            from app.document_processing.models import DocumentChunk
            chunks = (
                db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == job.document_id)
                .order_by(DocumentChunk.chunk_index.asc())
                .all()
            )
            if not chunks:
                raise ValueError(f"No chunks found for document {job.document_id}. Cannot run embedding.")

            total_chunks = len(chunks)
            logger.info("ProcessingWorker: Embedding %d chunks for document %s", total_chunks, job.document_id)

            # Initialize Embedding Service
            from app.services.embeddings import EmbeddingService
            embedding_svc = EmbeddingService()
            batch_size = embedding_svc.settings.embedding_batch_size

            all_embeddings = []
            embedding_start_time = time.time()

            # Process in batches
            for i in range(0, total_chunks, batch_size):
                # Support cancellation check
                db.refresh(job)
                if job.status == JobStatus.CANCELLED:
                    logger.info("ProcessingWorker: Embedding job %s cancelled", job_id)
                    return

                batch_chunks = chunks[i : i + batch_size]
                batch_texts = [c.chunk_text for c in batch_chunks]

                current_batch_num = i // batch_size + 1
                total_batches = math.ceil(total_chunks / batch_size)
                
                service.update_progress(
                    job_id=job_id,
                    percentage=int((i / total_chunks) * 90),
                    current_step=f"Generating Embeddings (Batch {current_batch_num} of {total_batches})",
                )

                # Thread-safe batch embedding execution in executor thread pool
                loop = asyncio.get_running_loop()
                batch_vectors = await loop.run_in_executor(
                    None,
                    embedding_svc.embed_batch,
                    batch_texts,
                )

                for idx, vector in enumerate(batch_vectors):
                    chunk = batch_chunks[idx]
                    all_embeddings.append({
                        "chunk_id": chunk.id,
                        "vector": vector,
                    })

            embedding_duration = time.time() - embedding_start_time

            # 4. Save results to DB
            service.update_progress(job_id, percentage=95, current_step="Saving Embeddings")
            db_save_start_time = time.time()

            # Safely replace old embeddings inside transaction
            db.query(DocumentEmbedding).filter(DocumentEmbedding.document_id == job.document_id).delete()

            for item in all_embeddings:
                doc_embedding = DocumentEmbedding(
                    document_id=job.document_id,
                    chunk_id=item["chunk_id"],
                    embedding_vector=item["vector"],
                    embedding_dimension=embedding_svc.dimension,
                    embedding_model=embedding_svc.model_name,
                    embedding_version=embedding_svc.version,
                )
                db.add(doc_embedding)

            db.commit()
            db_save_duration = time.time() - db_save_start_time

            # 5. Complete job
            service.mark_completed(job_id)
            worker_execution_time = time.time() - worker_execution_start_time

            # Save metrics
            self._save_embedding_performance_metrics(
                db=db,
                job=job,
                queue_wait_time=queue_wait_time,
                worker_execution_time=worker_execution_time,
                embedding_duration=embedding_duration,
                db_save_duration=db_save_duration,
            )

            # Auto-trigger vector database synchronization job after embedding generation completes successfully
            try:
                logger.info("ProcessingWorker: Auto-triggering Qdrant vector sync job for document %s", job.document_id)
                from app.services.vector_sync import VectorSyncService
                sync_svc = VectorSyncService(db, self._queue)
                await sync_svc.create_sync_job(
                    user_id=job.user_id,
                    document_id=job.document_id,
                    priority=job.priority.value if hasattr(job.priority, "value") else str(job.priority),
                )
            except Exception as e:
                logger.error("ProcessingWorker: Failed to auto-trigger vector sync job for document %s: %s", job.document_id, str(e))

            logger.info("ProcessingWorker: Embedding job %s completed successfully", job_id)

        except Exception as exc:
            logger.error("ProcessingWorker: Embedding job %s failed: %s", job_id, str(exc), exc_info=True)
            raise exc

    def _save_embedding_performance_metrics(
        self,
        db: Session,
        job: ProcessingJob,
        queue_wait_time: float,
        worker_execution_time: float,
        embedding_duration: float,
        db_save_duration: float,
    ):
        from app.models import AnalyticsRecord
        metrics = {
            "queue_wait_time": queue_wait_time,
            "worker_execution_time": worker_execution_time,
            "embedding_duration": embedding_duration,
            "database_save_duration": db_save_duration,
            "total_processing_duration": queue_wait_time + worker_execution_time,
        }
        for key, val in metrics.items():
            record = AnalyticsRecord(
                metric_name=key,
                metric_value=float(val),
                metric_unit="seconds",
                category="document_embedding",
                user_id=job.user_id,
                case_id=job.case_id,
                metadata_json=json.dumps({
                    "job_id": str(job.id),
                    "document_id": str(job.document_id),
                    "job_type": job.job_type.value,
                })
            )
            db.add(record)
        db.commit()

    async def _run_vector_sync_pipeline(self, service: ProcessingService, job: ProcessingJob) -> None:
        """Synchronizes generated embeddings for a document to Qdrant vector database."""
        job_id = job.id
        db = service.db
        worker_execution_start_time = time.time()
        created_timestamp = job.created_at.timestamp()
        queue_wait_time = max(0.0, worker_execution_start_time - created_timestamp)

        try:
            # 1. Transition PENDING/QUEUED → STARTING
            service.mark_starting(job_id)
            await asyncio.sleep(0.1)

            # 2. Transition STARTING → RUNNING
            service.mark_running(job_id)

            # 3. Synchronize vector embeddings
            from app.services.vector_sync import VectorSyncService
            sync_svc = VectorSyncService(db, self._queue)
            
            def progress_callback(percentage: int):
                service.update_progress(
                    job_id=job_id,
                    percentage=percentage,
                    current_step=f"Uploading Vector Batches ({percentage}%)",
                )

            await sync_svc.sync_document_vectors(
                job_id=job_id,
                document_id=job.document_id,
                progress_callback=progress_callback,
            )

            # 4. Transition RUNNING → COMPLETED
            service.mark_completed(job_id)
            worker_execution_time = time.time() - worker_execution_start_time

            # Save metrics
            self._save_sync_performance_metrics(
                db=db,
                job=job,
                queue_wait_time=queue_wait_time,
                worker_execution_time=worker_execution_time,
            )

            # Auto-trigger timeline extraction job after vector sync completes successfully
            try:
                from app.models import Document
                doc = db.get(Document, job.document_id)
                if doc and doc.case_id:
                    logger.info("ProcessingWorker: Auto-triggering timeline extraction job for document %s", job.document_id)
                    from app.processing.service import get_processing_service
                    proc_service = get_processing_service(db)
                    await proc_service.create_job(
                        user_id=job.user_id,
                        document_id=job.document_id,
                        job_type="timeline",
                        priority=job.priority.value if hasattr(job.priority, "value") else str(job.priority),
                    )
            except Exception as e:
                logger.error("ProcessingWorker: Failed to auto-trigger timeline extraction job: %s", str(e))

            logger.info("ProcessingWorker: Vector sync job %s completed successfully", job_id)

        except Exception as exc:
            logger.error("ProcessingWorker: Vector sync job %s failed: %s", job_id, str(exc), exc_info=True)
            raise exc

    def _save_sync_performance_metrics(
        self,
        db: Session,
        job: ProcessingJob,
        queue_wait_time: float,
        worker_execution_time: float,
    ):
        from app.models import AnalyticsRecord
        metrics = {
            "queue_wait_time": queue_wait_time,
            "worker_execution_time": worker_execution_time,
            "total_processing_duration": queue_wait_time + worker_execution_time,
        }
        for key, val in metrics.items():
            record = AnalyticsRecord(
                metric_name=key,
                metric_value=float(val),
                metric_unit="seconds",
                category="vector_synchronization",
                user_id=job.user_id,
                case_id=job.case_id,
                metadata_json=json.dumps({
                    "job_id": str(job.id),
                    "document_id": str(job.document_id),
                    "job_type": job.job_type.value,
                })
            )
            db.add(record)
        db.commit()




# ---------------------------------------------------------------------------
    async def _run_timeline_pipeline(self, service: ProcessingService, job: ProcessingJob) -> None:
        """Extracts and persists timeline events from document chunks."""
        job_id = job.id
        db = service.db
        worker_execution_start_time = time.time()
        created_timestamp = job.created_at.timestamp()
        queue_wait_time = max(0.0, worker_execution_start_time - created_timestamp)

        try:
            # 1. Transition PENDING/QUEUED → STARTING
            service.mark_starting(job_id)
            await asyncio.sleep(0.1)

            # 2. Transition STARTING → RUNNING
            service.mark_running(job_id)

            # 3. Fetch Case association
            from app.models import Document
            doc = db.get(Document, job.document_id)
            if not doc:
                raise ValueError(f"Associated document record {job.document_id} not found")
            if not doc.case_id:
                raise ValueError(f"Document {job.document_id} is not scoped to a case case_id")

            # 4. Progress step
            service.update_progress(job_id, percentage=30, current_step="Analyzing Chunks Context")

            from app.services.timeline import TimelineIntelligenceService
            timeline_svc = TimelineIntelligenceService(db)
            
            loop = asyncio.get_running_loop()
            service.update_progress(job_id, percentage=60, current_step="Extracting Legal Event Dates")
            
            await loop.run_in_executor(
                None,
                timeline_svc.extract_document_events,
                doc.case_id,
                job.document_id,
            )

            service.update_progress(job_id, percentage=95, current_step="Merging & Linking Related Events")

            # 5. Transition RUNNING → COMPLETED
            service.mark_completed(job_id)
            worker_execution_time = time.time() - worker_execution_start_time
            
            # Save metrics
            self._save_timeline_performance_metrics(
                db=db,
                job=job,
                queue_wait_time=queue_wait_time,
                worker_execution_time=worker_execution_time,
            )

            logger.info("ProcessingWorker: Timeline extraction job %s completed successfully", job_id)

        except Exception as exc:
            logger.error("ProcessingWorker: Timeline extraction job %s failed: %s", job_id, str(exc), exc_info=True)
            raise exc

    def _save_timeline_performance_metrics(
        self,
        db: Session,
        job: ProcessingJob,
        queue_wait_time: float,
        worker_execution_time: float,
    ):
        from app.models import AnalyticsRecord
        metrics = {
            "queue_wait_time": queue_wait_time,
            "worker_execution_time": worker_execution_time,
            "total_processing_duration": queue_wait_time + worker_execution_time,
        }
        for key, val in metrics.items():
            record = AnalyticsRecord(
                metric_name=key,
                metric_value=float(val),
                metric_unit="seconds",
                category="timeline_extraction",
                user_id=job.user_id,
                case_id=job.case_id,
                metadata_json=json.dumps({
                    "job_id": str(job.id),
                    "document_id": str(job.document_id),
                    "job_type": job.job_type.value,
                })
            )
            db.add(record)
        db.commit()


# ---------------------------------------------------------------------------
# Singleton worker instance
# ---------------------------------------------------------------------------

worker: ProcessingWorker = ProcessingWorker()
