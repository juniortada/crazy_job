"""Integration tests for dashboard actions."""

from __future__ import annotations

import pytest

from crazyjob.dashboard.core.factory import create_dashboard_actions, create_dashboard_queries


@pytest.mark.integration
def test_cancel_enqueued_job(backend, job_factory) -> None:
    job = job_factory.enqueue(backend)
    actions = create_dashboard_actions(backend)

    actions.cancel(job.id)

    record = backend.get_job(job.id)
    assert record is None  # deleted


@pytest.mark.integration
def test_pause_and_resume_queue(backend) -> None:
    actions = create_dashboard_actions(backend)

    actions.pause_queue("mailers")
    # Verify it's in the pauses table
    with backend._cursor() as cur:
        cur.execute("SELECT * FROM cj_queue_pauses WHERE queue = ?;", ("mailers",))
        assert cur.fetchone() is not None

    actions.resume_queue("mailers")
    with backend._cursor() as cur:
        cur.execute("SELECT * FROM cj_queue_pauses WHERE queue = ?;", ("mailers",))
        assert cur.fetchone() is None


@pytest.mark.integration
def test_clear_queue(backend, job_factory) -> None:
    job_factory.enqueue(backend, queue="test_queue")
    job_factory.enqueue(backend, queue="test_queue")
    actions = create_dashboard_actions(backend)

    actions.clear_queue("test_queue")

    queries = create_dashboard_queries(backend)
    jobs = queries.list_jobs(status="enqueued", queue="test_queue")
    assert len(jobs) == 0
