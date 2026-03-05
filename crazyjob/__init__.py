"""CrazyJob — Framework-agnostic background job processing for Python, powered by PostgreSQL."""
from __future__ import annotations

from crazyjob.core.exceptions import CrazyJobError, DeadJob, JobFailed, Retry
from crazyjob.core.job import Job
from crazyjob.core.scheduler import schedule

__all__ = [
    "Job",
    "schedule",
    "CrazyJobError",
    "JobFailed",
    "DeadJob",
    "Retry",
]
