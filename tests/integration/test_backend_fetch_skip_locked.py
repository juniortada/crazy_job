"""Integration tests for SKIP LOCKED fetch behavior."""

from __future__ import annotations

import threading

import pytest


@pytest.mark.integration
def test_two_workers_never_pick_same_job(backend, job_factory) -> None:
    """SKIP LOCKED must guarantee exclusive job consumption."""
    job = job_factory.enqueue(backend, queue="default")

    results: list = []

    def fetch(worker_id: str) -> None:
        result = backend.fetch_next(queues=["default"], worker_id=worker_id)
        results.append(result)

    t1 = threading.Thread(target=fetch, args=("worker-1",))
    t2 = threading.Thread(target=fetch, args=("worker-2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    fetched = [r for r in results if r is not None]
    assert len(fetched) == 1, "Exactly one worker should have fetched the job"
    assert fetched[0].id == job.id


@pytest.mark.integration
def test_fetch_next_increments_attempts(backend, job_factory) -> None:
    """fetch_next atomically claims the job AND increments attempts."""
    job_factory.enqueue(backend)
    fetched = backend.fetch_next(queues=["default"], worker_id="worker-1")

    assert fetched is not None
    assert fetched.attempts == 1
    assert fetched.status == "active"
    assert fetched.worker_id == "worker-1"
    assert fetched.started_at is not None


@pytest.mark.integration
def test_fetch_next_returns_none_on_empty_queue(backend) -> None:
    result = backend.fetch_next(queues=["default"], worker_id="worker-1")
    assert result is None


@pytest.mark.integration
def test_fetch_respects_priority(backend, job_factory) -> None:
    """Lower priority number = higher priority = fetched first."""
    job_factory.enqueue(backend, priority=50)
    high_priority = job_factory.enqueue(backend, priority=10)

    fetched = backend.fetch_next(queues=["default"], worker_id="worker-1")
    assert fetched is not None
    assert fetched.id == high_priority.id
