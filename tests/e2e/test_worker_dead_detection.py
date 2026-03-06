"""E2E test: dead worker detection re-enqueues jobs."""

from __future__ import annotations

import pytest

from crazyjob.core.job import WorkerRecord


@pytest.mark.e2e
def test_dead_worker_jobs_are_reenqueued(backend, job_factory) -> None:
    # Simulate a dead worker: register it, fetch a job, then stop heartbeating
    dead_worker = WorkerRecord(
        id="dead-worker:99999",
        queues=["default"],
        concurrency=1,
        status="busy",
    )
    backend.register_worker(dead_worker)

    job = job_factory.enqueue(backend)
    # Simulate the worker picking up the job
    backend.fetch_next(queues=["default"], worker_id="dead-worker:99999")

    # Manually age the heartbeat
    with backend._cursor() as cur:
        cur.execute(
            """
            UPDATE cj_workers
            SET last_beat_at = datetime('now', '-120 seconds')
            WHERE id = ?;
            """,
            ("dead-worker:99999",),
        )

    # Detect stale workers
    stale = backend.get_stale_workers(60)
    assert len(stale) >= 1

    # Re-enqueue the dead worker's jobs
    active_jobs = backend.get_active_jobs_for_worker("dead-worker:99999")
    for j in active_jobs:
        backend.reenqueue_job(j.id)

    record = backend.get_job(job.id)
    assert record.status == "enqueued"
