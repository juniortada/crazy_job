"""BackendDriver — the single interface between the core engine and any storage system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from crazyjob.core.job import DeadLetterRecord, JobRecord, WorkerRecord


class BackendDriver(ABC):
    """Abstract base class for storage backends.

    The core engine only talks to this interface. The PostgreSQL driver is the
    reference implementation.
    """

    @abstractmethod
    def enqueue(self, job: JobRecord) -> str:
        """Insert a new job. Returns job ID."""
        ...

    @abstractmethod
    def fetch_next(self, queues: list[str], worker_id: str) -> JobRecord | None:
        """Atomically fetch, lock, and claim the next job.

        Must increment attempts and set started_at in the SAME transaction.
        Never split this into two queries. See Queue Poisoning rules.
        """
        ...

    @abstractmethod
    def mark_completed(self, job_id: str, result: dict[str, object]) -> None:
        """Mark a job as completed with optional result data."""
        ...

    @abstractmethod
    def mark_failed(self, job_id: str, error: str, retry_at: datetime | None = None) -> None:
        """Mark a job as failed. If retry_at is set, status becomes 'retrying'."""
        ...

    @abstractmethod
    def move_to_dead(self, job_id: str, reason: str) -> None:
        """Move a job to the dead letters table."""
        ...

    @abstractmethod
    def register_worker(self, worker: WorkerRecord) -> None:
        """Register a new worker in the workers table."""
        ...

    @abstractmethod
    def heartbeat(self, worker_id: str) -> None:
        """Update the worker's last_beat_at timestamp."""
        ...

    @abstractmethod
    def deregister_worker(self, worker_id: str) -> None:
        """Remove a worker from the registry."""
        ...

    @abstractmethod
    def get_job(self, job_id: str) -> JobRecord | None:
        """Fetch a single job by ID."""
        ...

    @abstractmethod
    def get_dead_letter(self, job_id: str) -> DeadLetterRecord | None:
        """Fetch a dead letter by its original job ID."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close the backend connection(s)."""
        ...

    @abstractmethod
    def get_stale_workers(self, threshold_seconds: int) -> list[WorkerRecord]:
        """Find workers whose heartbeat is older than the threshold."""
        ...

    @abstractmethod
    def get_active_jobs_for_worker(self, worker_id: str) -> list[JobRecord]:
        """Get all active jobs assigned to a specific worker."""
        ...

    @abstractmethod
    def reenqueue_job(self, job_id: str) -> None:
        """Re-enqueue a job (e.g., from a dead worker)."""
        ...

    @abstractmethod
    def mark_worker_stopped(self, worker_id: str) -> None:
        """Mark a worker as stopped."""
        ...

    @abstractmethod
    def fetch_due_schedules(self) -> list[dict[str, object]]:
        """Fetch schedules that are due to run."""
        ...

    @abstractmethod
    def update_schedule_timestamps(
        self, schedule_id: str, last_run_at: datetime, next_run_at: datetime
    ) -> None:
        """Update a schedule's run timestamps after firing."""
        ...
