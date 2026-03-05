"""SQLite backend — dead letter tests."""
from __future__ import annotations

import pytest


@pytest.mark.integration
class TestSQLiteDeadLetters:
    def test_move_to_dead(self, sqlite_backend, job_factory):
        record = job_factory.enqueue(sqlite_backend)
        job = sqlite_backend.fetch_next(["default"], "worker-1")
        assert job is not None

        sqlite_backend.move_to_dead(job.id, "max attempts exceeded")

        updated = sqlite_backend.get_job(job.id)
        assert updated is not None
        assert updated.status == "dead"

        dead = sqlite_backend.get_dead_letter(job.id)
        assert dead is not None
        assert dead.reason == "max attempts exceeded"
        assert dead.original_job["id"] == job.id

    def test_get_dead_letter_returns_none_for_unknown(self, sqlite_backend):
        result = sqlite_backend.get_dead_letter("nonexistent-id")
        assert result is None
