"""E2E test: worker graceful shutdown."""

from __future__ import annotations

import threading
import time

import pytest

from crazyjob.core.worker import Worker


@pytest.mark.e2e
def test_worker_graceful_shutdown(backend, job_factory) -> None:
    job_factory.enqueue(backend, class_path="tests.helpers.jobs.SlowJob")

    worker = Worker(
        backend=backend,
        queues=["default"],
        concurrency=1,
        shutdown_timeout=1,
    )
    thread = threading.Thread(target=worker.run)
    thread.start()

    time.sleep(0.5)
    worker.shutdown()
    thread.join(timeout=5)

    # Worker should have stopped
    assert not worker._running
