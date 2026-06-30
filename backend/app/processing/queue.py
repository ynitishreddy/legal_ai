"""
app.processing.queue — Queue abstraction for background processing.

Design contract:
  - InMemoryProcessingQueue implements the abstract interface.
  - Future phases can swap this with a Redis/Celery implementation
    by providing a class that satisfies the same interface.
  - No service or route code needs to change on migration.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import Deque, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class AbstractProcessingQueue(ABC):
    """
    Abstract contract for a processing job queue.

    Any concrete implementation (in-memory, Redis, Celery, etc.)
    must satisfy these methods so the service layer stays unchanged.
    """

    @abstractmethod
    async def enqueue(self, job_id: UUID) -> None:
        """Add a job to the back of the queue."""

    @abstractmethod
    async def dequeue(self) -> Optional[UUID]:
        """Remove and return the front job ID, or None if empty."""

    @abstractmethod
    async def peek(self) -> Optional[UUID]:
        """Return the front job ID without removing it, or None if empty."""

    @abstractmethod
    async def cancel(self, job_id: UUID) -> bool:
        """
        Remove a job from the queue (if present).
        Returns True if it was found and removed, False otherwise.
        """

    @abstractmethod
    async def retry(self, job_id: UUID) -> None:
        """Re-add a failed job to the back of the queue."""

    @abstractmethod
    async def get_position(self, job_id: UUID) -> Optional[int]:
        """Return 1-based queue position, or None if not in queue."""

    @abstractmethod
    async def size(self) -> int:
        """Return the current number of items in the queue."""

    @abstractmethod
    async def contains(self, job_id: UUID) -> bool:
        """Return True if the job is currently waiting in the queue."""


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------

class InMemoryProcessingQueue(AbstractProcessingQueue):
    """
    Thread-safe in-memory FIFO queue backed by asyncio.Lock.

    Suitable for single-process deployments and development.
    Swap for a Redis/Celery implementation in production multi-worker setups.
    """

    def __init__(self) -> None:
        self._queue: Deque[UUID] = deque()
        self._lock: asyncio.Lock = asyncio.Lock()

    async def enqueue(self, job_id: UUID) -> None:
        """Add job_id to the back of the queue."""
        async with self._lock:
            if job_id not in self._queue:
                self._queue.append(job_id)
                logger.debug("Queue.enqueue: job=%s  size=%d", job_id, len(self._queue))
            else:
                logger.warning("Queue.enqueue: job=%s already in queue — skipped", job_id)

    async def dequeue(self) -> Optional[UUID]:
        """Remove and return the front item, or None if empty."""
        async with self._lock:
            if not self._queue:
                return None
            job_id = self._queue.popleft()
            logger.debug("Queue.dequeue: job=%s  remaining=%d", job_id, len(self._queue))
            return job_id

    async def peek(self) -> Optional[UUID]:
        """Return the front item without removing it."""
        async with self._lock:
            return self._queue[0] if self._queue else None

    async def cancel(self, job_id: UUID) -> bool:
        """Remove a specific job from the queue. Returns True if found."""
        async with self._lock:
            try:
                self._queue.remove(job_id)
                logger.debug("Queue.cancel: removed job=%s  remaining=%d", job_id, len(self._queue))
                return True
            except ValueError:
                return False

    async def retry(self, job_id: UUID) -> None:
        """Re-add a job to the back of the queue."""
        async with self._lock:
            if job_id not in self._queue:
                self._queue.append(job_id)
                logger.debug("Queue.retry: re-enqueued job=%s  size=%d", job_id, len(self._queue))

    async def get_position(self, job_id: UUID) -> Optional[int]:
        """Return 1-based position, or None if not found."""
        async with self._lock:
            for i, jid in enumerate(self._queue):
                if jid == job_id:
                    return i + 1
            return None

    async def size(self) -> int:
        """Current queue depth."""
        async with self._lock:
            return len(self._queue)

    async def contains(self, job_id: UUID) -> bool:
        """Check membership without modifying the queue."""
        async with self._lock:
            return job_id in self._queue


# ---------------------------------------------------------------------------
# Singleton instance — injected into the worker and service
# ---------------------------------------------------------------------------

processing_queue: InMemoryProcessingQueue = InMemoryProcessingQueue()
