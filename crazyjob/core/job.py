"""Core job models and base Job class."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, ClassVar
from uuid import uuid4


@dataclass
class JobRecord:
    """Canonical in-memory representation of a job. Used everywhere between layers."""

    class_path: str
    args: list
    kwargs: dict
    queue: str = "default"
    priority: int = 50
    max_attempts: int = 3
    id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "enqueued"
    attempts: int = 0
    run_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    error: str | None = None
    worker_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    meta: dict = field(default_factory=dict)


@dataclass
class WorkerRecord:
    """In-memory representation of a registered worker."""

    id: str  # hostname:PID
    queues: list[str]
    concurrency: int
    status: str = "idle"  # idle | busy | stopped
    current_job_id: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    last_beat_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DeadLetterRecord:
    """A job that exhausted all retry attempts."""

    id: str
    original_job: dict  # full JobRecord snapshot as dict
    reason: str
    killed_at: datetime
    resurrected_at: datetime | None = None


class Job:
    """Base class for all CrazyJob jobs.

    Subclass this and implement ``perform()`` with your business logic.
    """

    # Class-level configuration — override in subclasses
    queue: ClassVar[str] = "default"
    max_attempts: ClassVar[int] = 3
    retry_backoff: ClassVar[str | callable] = "exponential"
    retry_jitter: ClassVar[bool] = True
    timeout: ClassVar[timedelta | None] = None
    priority: ClassVar[int] = 50

    def perform(self, *args: Any, **kwargs: Any) -> None:
        """Execute the job. Override this in subclasses."""
        raise NotImplementedError

    @classmethod
    def enqueue(cls, *args: Any, **kwargs: Any) -> str:
        """Enqueue this job for immediate processing."""
        from crazyjob.core.client import get_client

        return get_client().enqueue(cls, args=list(args), kwargs=kwargs)

    @classmethod
    def enqueue_in(cls, delay: timedelta, *args: Any, **kwargs: Any) -> str:
        """Enqueue this job to run after the given delay."""
        from crazyjob.core.client import get_client

        return get_client().enqueue(cls, args=list(args), kwargs=kwargs, delay=delay)

    @classmethod
    def enqueue_at(cls, run_at: datetime, *args: Any, **kwargs: Any) -> str:
        """Enqueue this job to run at a specific time."""
        from crazyjob.core.client import get_client

        return get_client().enqueue(cls, args=list(args), kwargs=kwargs, run_at=run_at)

    @classmethod
    def _class_path(cls) -> str:
        """Return the fully-qualified dotted import path for this job class."""
        return f"{cls.__module__}.{cls.__qualname__}"
