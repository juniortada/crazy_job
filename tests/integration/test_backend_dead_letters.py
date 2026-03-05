"""Integration tests for dead letter operations."""
from __future__ import annotations

import pytest


@pytest.mark.integration
def test_move_to_dead(backend, job_factory) -> None:
    job = job_factory.enqueue(backend, max_attempts=1)
    backend.fetch_next(queues=["default"], worker_id="worker-1")

    backend.move_to_dead(job.id, reason="Exhausted retries")

    record = backend.get_job(job.id)
    assert record.status == "dead"

    dead = backend.get_dead_letter(job.id)
    assert dead is not None
    assert dead.reason == "Exhausted retries"


@pytest.mark.integration
def test_get_dead_letter_returns_none_for_alive_job(backend, job_factory) -> None:
    job = job_factory.enqueue(backend)
    dead = backend.get_dead_letter(job.id)
    assert dead is None
