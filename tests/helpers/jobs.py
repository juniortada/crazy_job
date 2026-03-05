"""Test helper job classes for E2E tests."""
from __future__ import annotations

import time

from crazyjob import Job


class NoOpJob(Job):
    """A job that does nothing — succeeds immediately."""

    queue = "default"

    def perform(self) -> None:
        pass


class FailOnceJob(Job):
    """A job that fails on the first attempt, then succeeds."""

    queue = "default"
    max_attempts = 3
    _call_count: int = 0

    def perform(self) -> None:
        FailOnceJob._call_count += 1
        if FailOnceJob._call_count == 1:
            raise RuntimeError("Intentional failure on first attempt")


class AlwaysFailJob(Job):
    """A job that always fails."""

    queue = "default"
    max_attempts = 3

    def perform(self) -> None:
        raise RuntimeError("Always fails")


class SlowJob(Job):
    """A job that takes a long time — useful for shutdown tests."""

    queue = "default"

    def perform(self) -> None:
        time.sleep(60)
