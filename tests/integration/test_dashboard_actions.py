"""Integration tests for dashboard actions."""

from __future__ import annotations

import pytest

from crazyjob.dashboard.core.actions import DashboardActions


@pytest.mark.integration
def test_cancel_enqueued_job(backend, job_factory) -> None:
    job = job_factory.enqueue(backend)
    actions = DashboardActions(backend)

    actions.cancel(job.id)

    record = backend.get_job(job.id)
    assert record is None  # deleted


@pytest.mark.integration
def test_pause_and_resume_queue(backend) -> None:
    actions = DashboardActions(backend)

    actions.pause_queue("mailers")
    # Verify it's in the pauses table
    with backend._cursor() as cur:
        cur.execute("SELECT * FROM cj_queue_pauses WHERE queue = %s;", ("mailers",))
        assert cur.fetchone() is not None

    actions.resume_queue("mailers")
    with backend._cursor() as cur:
        cur.execute("SELECT * FROM cj_queue_pauses WHERE queue = %s;", ("mailers",))
        assert cur.fetchone() is None


@pytest.mark.integration
def test_clear_queue(backend, job_factory) -> None:
    job_factory.enqueue(backend, queue="test_queue")
    job_factory.enqueue(backend, queue="test_queue")
    actions = DashboardActions(backend)

    actions.clear_queue("test_queue")

    from crazyjob.dashboard.core.queries import DashboardQueries

    queries = DashboardQueries(backend)
    jobs = queries.list_jobs(status="enqueued", queue="test_queue")
    assert len(jobs) == 0
