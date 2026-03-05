"""Shared test fixtures for CrazyJob."""
from __future__ import annotations

import pytest

from crazyjob.core.job import JobRecord


@pytest.fixture()
def job_factory():
    """Factory for creating JobRecord instances in tests."""

    class _Factory:
        def create(
            self,
            queue: str = "default",
            class_path: str = "tests.helpers.jobs.NoOpJob",
            args: list | None = None,
            kwargs: dict | None = None,
            max_attempts: int = 3,
            priority: int = 50,
        ) -> JobRecord:
            return JobRecord(
                class_path=class_path,
                args=args or [],
                kwargs=kwargs or {},
                queue=queue,
                max_attempts=max_attempts,
                priority=priority,
            )

        def enqueue(
            self,
            backend,
            queue: str = "default",
            class_path: str = "tests.helpers.jobs.NoOpJob",
            args: list | None = None,
            kwargs: dict | None = None,
            max_attempts: int = 3,
            priority: int = 50,
        ) -> JobRecord:
            record = self.create(
                queue=queue,
                class_path=class_path,
                args=args,
                kwargs=kwargs,
                max_attempts=max_attempts,
                priority=priority,
            )
            job_id = backend.enqueue(record)
            record.id = job_id
            return record

    return _Factory()
