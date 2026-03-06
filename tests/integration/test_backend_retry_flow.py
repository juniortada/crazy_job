"""Integration tests for retry flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.integration
def test_mark_failed_with_retry_at(backend, job_factory) -> None:
    job = job_factory.enqueue(backend)
    backend.fetch_next(queues=["default"], worker_id="worker-1")

    retry_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
    backend.mark_failed(job.id, error="Temporary failure", retry_at=retry_at)

    record = backend.get_job(job.id)
    assert record.status == "retrying"
    assert "Temporary failure" in record.error
    assert record.run_at is not None


@pytest.mark.integration
def test_mark_failed_without_retry(backend, job_factory) -> None:
    job = job_factory.enqueue(backend)
    backend.fetch_next(queues=["default"], worker_id="worker-1")

    backend.mark_failed(job.id, error="Permanent failure")

    record = backend.get_job(job.id)
    assert record.status == "failed"
    assert "Permanent failure" in record.error


@pytest.mark.integration
def test_mark_completed(backend, job_factory) -> None:
    job = job_factory.enqueue(backend)
    backend.fetch_next(queues=["default"], worker_id="worker-1")
    backend.mark_completed(job.id, result={})

    record = backend.get_job(job.id)
    assert record.status == "completed"
    assert record.completed_at is not None
