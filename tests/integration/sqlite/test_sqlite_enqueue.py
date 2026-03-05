"""SQLite backend — enqueue tests."""
from __future__ import annotations

import pytest

from crazyjob.core.job import JobRecord


@pytest.mark.integration
class TestSQLiteEnqueue:
    def test_enqueue_returns_job_id(self, sqlite_backend, job_factory):
        record = job_factory.enqueue(sqlite_backend)
        assert record.id is not None
        assert len(record.id) == 36  # UUID format

    def test_enqueued_job_has_correct_initial_state(self, sqlite_backend, job_factory):
        record = job_factory.enqueue(sqlite_backend, queue="mailers")
        job = sqlite_backend.get_job(record.id)
        assert job is not None
        assert job.status == "enqueued"
        assert job.queue == "mailers"
        assert job.attempts == 0

    def test_enqueue_with_args_and_kwargs(self, sqlite_backend, job_factory):
        record = job_factory.enqueue(
            sqlite_backend,
            args=[1, "hello"],
            kwargs={"key": "value"},
        )
        job = sqlite_backend.get_job(record.id)
        assert job is not None
        assert job.args == [1, "hello"]
        assert job.kwargs == {"key": "value"}

    def test_enqueue_preserves_priority(self, sqlite_backend, job_factory):
        record = job_factory.enqueue(sqlite_backend, priority=10)
        job = sqlite_backend.get_job(record.id)
        assert job is not None
        assert job.priority == 10
