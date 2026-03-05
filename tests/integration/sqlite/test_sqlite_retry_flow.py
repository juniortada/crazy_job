"""SQLite backend — retry flow tests."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest


@pytest.mark.integration
class TestSQLiteRetryFlow:
    def test_mark_failed_with_retry(self, sqlite_backend, job_factory):
        record = job_factory.enqueue(sqlite_backend)
        job = sqlite_backend.fetch_next(["default"], "worker-1")
        assert job is not None

        retry_at = datetime.utcnow() + timedelta(seconds=30)
        sqlite_backend.mark_failed(job.id, "temporary error", retry_at=retry_at)

        updated = sqlite_backend.get_job(job.id)
        assert updated is not None
        assert updated.status == "retrying"
        assert updated.error == "temporary error"

    def test_mark_failed_without_retry(self, sqlite_backend, job_factory):
        record = job_factory.enqueue(sqlite_backend)
        job = sqlite_backend.fetch_next(["default"], "worker-1")
        assert job is not None

        sqlite_backend.mark_failed(job.id, "permanent error")

        updated = sqlite_backend.get_job(job.id)
        assert updated is not None
        assert updated.status == "failed"

    def test_mark_completed(self, sqlite_backend, job_factory):
        record = job_factory.enqueue(sqlite_backend)
        job = sqlite_backend.fetch_next(["default"], "worker-1")
        assert job is not None

        sqlite_backend.mark_completed(job.id, {"result": "ok"})

        updated = sqlite_backend.get_job(job.id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.completed_at is not None
