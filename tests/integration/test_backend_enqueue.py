"""Integration tests for backend enqueue operations."""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_enqueue_sets_correct_initial_state(backend, job_factory) -> None:
    job = job_factory.enqueue(backend, queue="mailers", kwargs={"user_id": 42})

    record = backend.get_job(job.id)
    assert record.status == "enqueued"
    assert record.attempts == 0
    assert record.kwargs == {"user_id": 42}
    assert record.queue == "mailers"
    assert record.started_at is None


@pytest.mark.integration
def test_enqueue_returns_valid_uuid(backend, job_factory) -> None:
    job = job_factory.enqueue(backend)
    assert job.id is not None
    assert len(job.id) == 36  # UUID format
