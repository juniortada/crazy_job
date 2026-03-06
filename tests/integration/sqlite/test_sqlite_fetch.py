"""SQLite backend — fetch_next tests (serialized writers)."""

from __future__ import annotations

import threading

import pytest


@pytest.mark.integration
class TestSQLiteFetchNext:
    def test_fetch_returns_none_on_empty_queue(self, sqlite_backend):
        result = sqlite_backend.fetch_next(["default"], "worker-1")
        assert result is None

    def test_fetch_claims_job_atomically(self, sqlite_backend, job_factory):
        job_factory.enqueue(sqlite_backend)
        job = sqlite_backend.fetch_next(["default"], "worker-1")
        assert job is not None
        assert job.status == "active"
        assert job.worker_id == "worker-1"
        assert job.attempts == 1

    def test_fetch_respects_priority(self, sqlite_backend, job_factory):
        job_factory.enqueue(sqlite_backend, priority=100)
        high = job_factory.enqueue(sqlite_backend, priority=1)

        fetched = sqlite_backend.fetch_next(["default"], "worker-1")
        assert fetched is not None
        assert fetched.id == high.id

    def test_fetch_respects_queue_filter(self, sqlite_backend, job_factory):
        job_factory.enqueue(sqlite_backend, queue="other")
        job_factory.enqueue(sqlite_backend, queue="target")

        fetched = sqlite_backend.fetch_next(["target"], "worker-1")
        assert fetched is not None
        assert fetched.queue == "target"

    def test_two_threads_never_get_same_job(self, sqlite_backend, job_factory):
        """BEGIN IMMEDIATE + Lock serializes writers so no duplicate claims."""
        job_factory.enqueue(sqlite_backend)
        results: list = []

        def fetch(worker_id: str) -> None:
            result = sqlite_backend.fetch_next(["default"], worker_id)
            results.append(result)

        t1 = threading.Thread(target=fetch, args=("w1",))
        t2 = threading.Thread(target=fetch, args=("w2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        non_none = [r for r in results if r is not None]
        assert len(non_none) == 1

    def test_fetch_skips_scheduled_future_jobs(self, sqlite_backend, job_factory):
        from datetime import datetime, timedelta, timezone

        record = job_factory.create()
        record.run_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        record.status = "enqueued"
        sqlite_backend.enqueue(record)

        fetched = sqlite_backend.fetch_next(["default"], "worker-1")
        assert fetched is None
