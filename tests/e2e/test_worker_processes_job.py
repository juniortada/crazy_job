"""E2E test: worker picks up and completes a job."""
from __future__ import annotations

import threading

import pytest

from crazyjob.core.worker import Worker


@pytest.mark.e2e
def test_worker_marks_job_completed_on_success(backend, job_factory) -> None:
    job = job_factory.enqueue(backend, class_path="tests.helpers.jobs.NoOpJob")

    worker = Worker(backend=backend, queues=["default"], concurrency=1)
    thread = threading.Thread(target=lambda: worker.run(max_jobs=1))
    thread.start()
    thread.join(timeout=10)

    record = backend.get_job(job.id)
    assert record.status == "completed"
    assert record.completed_at is not None
