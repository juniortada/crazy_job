"""SQLite dashboard queries tests."""

from __future__ import annotations

import pytest

from crazyjob.dashboard.core.sqlite_queries import SQLiteDashboardQueries


@pytest.mark.integration
class TestSQLiteDashboardQueries:
    def test_overview_stats_empty(self, sqlite_backend):
        queries = SQLiteDashboardQueries(sqlite_backend)
        stats = queries.overview_stats()
        assert stats["counts"] == {}
        assert stats["throughput"] == 0.0
        assert stats["error_rate"] == 0.0

    def test_overview_stats_with_jobs(self, sqlite_backend, job_factory):
        job_factory.enqueue(sqlite_backend)
        job_factory.enqueue(sqlite_backend)

        queries = SQLiteDashboardQueries(sqlite_backend)
        stats = queries.overview_stats()
        assert stats["counts"].get("enqueued", 0) == 2

    def test_list_jobs(self, sqlite_backend, job_factory):
        job_factory.enqueue(sqlite_backend)

        queries = SQLiteDashboardQueries(sqlite_backend)
        jobs = queries.list_jobs(status="enqueued")
        assert len(jobs) == 1

    def test_list_workers_empty(self, sqlite_backend):
        queries = SQLiteDashboardQueries(sqlite_backend)
        workers = queries.list_workers()
        assert workers == []

    def test_list_schedules_empty(self, sqlite_backend):
        queries = SQLiteDashboardQueries(sqlite_backend)
        schedules = queries.list_schedules()
        assert schedules == []
