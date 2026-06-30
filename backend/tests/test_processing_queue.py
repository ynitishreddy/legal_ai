"""
Tests for the in-memory processing queue implementation.

Validates all abstract interface methods work correctly.
"""

import asyncio
import uuid

import pytest

from app.processing.queue import InMemoryProcessingQueue


@pytest.fixture
def queue() -> InMemoryProcessingQueue:
    return InMemoryProcessingQueue()


@pytest.fixture
def job_id() -> uuid.UUID:
    return uuid.uuid4()


# ── enqueue ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enqueue_increases_size(queue, job_id):
    assert await queue.size() == 0
    await queue.enqueue(job_id)
    assert await queue.size() == 1


@pytest.mark.asyncio
async def test_enqueue_duplicate_is_idempotent(queue, job_id):
    await queue.enqueue(job_id)
    await queue.enqueue(job_id)  # duplicate — should be silently ignored
    assert await queue.size() == 1


@pytest.mark.asyncio
async def test_enqueue_multiple_jobs(queue):
    ids = [uuid.uuid4() for _ in range(5)]
    for jid in ids:
        await queue.enqueue(jid)
    assert await queue.size() == 5


# ── dequeue ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dequeue_empty_returns_none(queue):
    result = await queue.dequeue()
    assert result is None


@pytest.mark.asyncio
async def test_dequeue_is_fifo(queue):
    ids = [uuid.uuid4() for _ in range(3)]
    for jid in ids:
        await queue.enqueue(jid)

    for expected in ids:
        result = await queue.dequeue()
        assert result == expected


@pytest.mark.asyncio
async def test_dequeue_reduces_size(queue, job_id):
    await queue.enqueue(job_id)
    await queue.dequeue()
    assert await queue.size() == 0


# ── peek ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_peek_returns_front_without_removing(queue, job_id):
    await queue.enqueue(job_id)
    peeked = await queue.peek()
    assert peeked == job_id
    assert await queue.size() == 1  # still in queue


@pytest.mark.asyncio
async def test_peek_empty_returns_none(queue):
    assert await queue.peek() is None


# ── cancel ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_existing_job(queue, job_id):
    await queue.enqueue(job_id)
    removed = await queue.cancel(job_id)
    assert removed is True
    assert await queue.size() == 0


@pytest.mark.asyncio
async def test_cancel_nonexistent_job_returns_false(queue, job_id):
    removed = await queue.cancel(job_id)
    assert removed is False


@pytest.mark.asyncio
async def test_cancel_middle_of_queue(queue):
    ids = [uuid.uuid4() for _ in range(3)]
    for jid in ids:
        await queue.enqueue(jid)
    await queue.cancel(ids[1])
    assert await queue.size() == 2
    first = await queue.dequeue()
    assert first == ids[0]
    second = await queue.dequeue()
    assert second == ids[2]


# ── retry ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_adds_to_back(queue):
    id1, id2 = uuid.uuid4(), uuid.uuid4()
    await queue.enqueue(id1)
    await queue.enqueue(id2)
    await queue.dequeue()  # remove id1

    await queue.retry(id1)  # re-add id1 to back
    assert await queue.size() == 2

    first = await queue.dequeue()
    assert first == id2  # id2 still at front

    second = await queue.dequeue()
    assert second == id1  # id1 retried at back


# ── get_position ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_position(queue):
    ids = [uuid.uuid4() for _ in range(3)]
    for jid in ids:
        await queue.enqueue(jid)

    assert await queue.get_position(ids[0]) == 1
    assert await queue.get_position(ids[1]) == 2
    assert await queue.get_position(ids[2]) == 3


@pytest.mark.asyncio
async def test_get_position_not_in_queue(queue, job_id):
    assert await queue.get_position(job_id) is None


# ── contains ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_contains_true(queue, job_id):
    await queue.enqueue(job_id)
    assert await queue.contains(job_id) is True


@pytest.mark.asyncio
async def test_contains_false(queue, job_id):
    assert await queue.contains(job_id) is False


# ── size ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_size_empty(queue):
    assert await queue.size() == 0


@pytest.mark.asyncio
async def test_size_after_operations(queue):
    ids = [uuid.uuid4() for _ in range(4)]
    for jid in ids:
        await queue.enqueue(jid)
    await queue.dequeue()
    await queue.cancel(ids[2])
    assert await queue.size() == 2  # ids[1] and ids[3] remain
