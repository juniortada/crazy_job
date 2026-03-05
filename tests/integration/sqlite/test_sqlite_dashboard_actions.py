"""SQLite dashboard actions tests."""
from __future__ import annotations

import pytest

from crazyjob.dashboard.core.sqlite_actions import SQLiteDashboardActions


@pytest.mark.integration
class TestSQLiteDashboardActions:
    def test_cancel_enqueued_job(self, sqlite_backend, job_factory):
        record = job_factory.enqueue(sqlite_backend)

        actions = SQLiteDashboardActions(sqlite_backend)
        actions.cancel(record.id)

        job = sqlite_backend.get_job(record.id)
        assert job is None

    def test_pause_and_resume_queue(self, sqlite_backend):
        actions = SQLiteDashboardActions(sqlite_backend)
        actions.pause_queue("mailers")

        with sqlite_backend._cursor() as cur:
            cur.execute("SELECT * FROM cj_queue_pauses WHERE queue = ?;", ("mailers",))
            assert cur.fetchone() is not None

        actions.resume_queue("mailers")

        with sqlite_backend._cursor() as cur:
            cur.execute("SELECT * FROM cj_queue_pauses WHERE queue = ?;", ("mailers",))
            assert cur.fetchone() is None

    def test_clear_queue(self, sqlite_backend, job_factory):
        job_factory.enqueue(sqlite_backend, queue="to_clear")
        job_factory.enqueue(sqlite_backend, queue="to_clear")
        job_factory.enqueue(sqlite_backend, queue="keep")

        actions = SQLiteDashboardActions(sqlite_backend)
        actions.clear_queue("to_clear")

        from crazyjob.dashboard.core.sqlite_queries import SQLiteDashboardQueries

        queries = SQLiteDashboardQueries(sqlite_backend)
        jobs = queries.list_jobs(status="enqueued", queue="to_clear")
        assert len(jobs) == 0

        kept = queries.list_jobs(status="enqueued", queue="keep")
        assert len(kept) == 1

    def test_resurrect_dead_letter(self, sqlite_backend, job_factory):
        record = job_factory.enqueue(sqlite_backend)
        job = sqlite_backend.fetch_next(["default"], "worker-1")
        assert job is not None
        sqlite_backend.move_to_dead(job.id, "test reason")

        dead = sqlite_backend.get_dead_letter(job.id)
        assert dead is not None

        actions = SQLiteDashboardActions(sqlite_backend)
        new_id = actions.resurrect(dead.id)

        new_job = sqlite_backend.get_job(new_id)
        assert new_job is not None
        assert new_job.status == "enqueued"
        assert new_job.attempts == 0
