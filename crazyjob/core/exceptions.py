"""CrazyJob exception hierarchy."""
from __future__ import annotations


class CrazyJobError(Exception):
    """Base exception for all CrazyJob errors."""


class JobFailed(CrazyJobError):
    """Raised when a job fails during execution."""

    def __init__(self, job_id: str, error: str) -> None:
        self.job_id = job_id
        self.error = error
        super().__init__(f"Job {job_id} failed: {error}")


class DeadJob(CrazyJobError):
    """Raised when a job exhausts all retry attempts."""

    def __init__(self, job_id: str, reason: str) -> None:
        self.job_id = job_id
        self.reason = reason
        super().__init__(f"Job {job_id} is dead: {reason}")


class Retry(CrazyJobError):
    """Raise inside perform() to force an immediate retry.

    Optionally specify a delay in seconds.
    """

    def __init__(
        self, in_seconds: int | None = None, reason: str | None = None
    ) -> None:
        self.in_seconds = in_seconds
        self.reason = reason
        msg = reason or "Retry requested"
        if in_seconds is not None:
            msg += f" (in {in_seconds}s)"
        super().__init__(msg)


class ConfigurationError(CrazyJobError):
    """Raised for invalid configuration values."""
