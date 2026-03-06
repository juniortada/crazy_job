"""E2E test: scheduler fires a cron job."""

from __future__ import annotations

import pytest

from crazyjob.core.scheduler import Scheduler


@pytest.mark.e2e
def test_scheduler_fires_due_schedule(backend) -> None:
    # Insert a schedule that's due now
    with backend._cursor() as cur:
        cur.execute(
            """
            INSERT INTO cj_schedules (id, name, cron, class_path, args, kwargs, enabled, next_run_at)
            VALUES (?, ?, ?, ?, '[]', '{}', TRUE, datetime('now', '-1 minute'));
            """,
            ("sched-test-1", "test_schedule", "* * * * *", "tests.helpers.jobs.NoOpJob"),
        )

    scheduler = Scheduler(backend=backend, poll_interval=0.1)
    # Run just one tick
    scheduler._tick()

    # Verify a job was enqueued
    with backend._cursor() as cur:
        cur.execute(
            "SELECT * FROM cj_jobs WHERE class_path = ?;",
            ("tests.helpers.jobs.NoOpJob",),
        )
        rows = cur.fetchall()
        assert len(rows) >= 1

    # Verify the schedule was updated
    with backend._cursor() as cur:
        cur.execute("SELECT * FROM cj_schedules WHERE name = ?;", ("test_schedule",))
        schedule = cur.fetchone()
        assert schedule["last_run_at"] is not None
        assert schedule["next_run_at"] is not None
