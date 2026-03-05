"""Integration tests for dashboard queries."""

from __future__ import annotations

import pytest

from crazyjob.dashboard.core.queries import DashboardQueries


@pytest.mark.integration
def test_overview_stats_empty(backend) -> None:
    queries = DashboardQueries(backend)
    stats = queries.overview_stats()
    assert stats["throughput"] == 0.0
    assert stats["error_rate"] == 0.0


@pytest.mark.integration
def test_list_jobs_by_status(backend, job_factory) -> None:
    job_factory.enqueue(backend, queue="default")
    job_factory.enqueue(backend, queue="mailers")

    queries = DashboardQueries(backend)
    jobs = queries.list_jobs(status="enqueued")
    assert len(jobs) == 2


@pytest.mark.integration
def test_list_workers_empty(backend) -> None:
    queries = DashboardQueries(backend)
    workers = queries.list_workers()
    assert workers == []
