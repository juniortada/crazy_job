"""E2E test: worker retries a failed job."""
from __future__ import annotations

import threading

import pytest

from crazyjob.core.worker import Worker


@pytest.mark.e2e
def test_worker_retries_failed_job(backend, job_factory) -> None:
    from tests.helpers.jobs import FailOnceJob

    FailOnceJob._call_count = 0  # reset
    job = job_factory.enqueue(
        backend,
        class_path="tests.helpers.jobs.FailOnceJob",
        max_attempts=3,
    )

    worker = Worker(
        backend=backend,
        queues=["default"],
        concurrency=1,
        poll_interval=0.1,
    )
    thread = threading.Thread(target=lambda: worker.run(max_jobs=2))
    thread.start()
    thread.join(timeout=20)

    record = backend.get_job(job.id)
    # After first fail + retry, job should be completed or retrying
    assert record.status in ("completed", "retrying")
