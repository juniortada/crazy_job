"""Client for enqueueing jobs into the backend."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from crazyjob.core.exceptions import ConfigurationError
from crazyjob.core.job import Job, JobRecord
from crazyjob.core.serializer import Serializer

if TYPE_CHECKING:
    from crazyjob.backends.base import BackendDriver

logger = logging.getLogger(__name__)

# Global client singleton
_client: Client | None = None


class Client:
    """Enqueue jobs into the backend with validation."""

    def __init__(self, backend: BackendDriver) -> None:
        self.backend = backend

    def enqueue(
        self,
        job_class: type[Job],
        args: list[object] | None = None,
        kwargs: dict[str, object] | None = None,
        delay: timedelta | None = None,
        run_at: datetime | None = None,
    ) -> str:
        """Enqueue a job for processing.

        Validates max_attempts and argument serializability before touching
        the database. Raises ConfigurationError for invalid configurations.
        """
        args = args or []
        kwargs = kwargs or {}

        # Hard validation — raise before touching the database
        if job_class.max_attempts < 1:
            raise ConfigurationError(
                f"{job_class.__name__}.max_attempts must be >= 1, "
                f"got {job_class.max_attempts}. "
                f"A value of 0 would cause the job to loop forever on failure "
                f"(queue poisoning)."
            )

        # Validate args are serializable now, not at execution time
        try:
            Serializer.dumps({"args": args, "kwargs": kwargs})
        except TypeError as e:
            raise ConfigurationError(
                f"Job arguments for {job_class.__name__} are not serializable: {e}. "
                f"Pass only JSON-compatible types (str, int, float, bool, list, dict, "
                f"datetime, UUID). Do not pass ORM model instances."
            ) from e

        computed_run_at = _resolve_run_at(delay, run_at)

        record = JobRecord(
            class_path=job_class._class_path(),
            args=args,
            kwargs=kwargs,
            queue=job_class.queue,
            priority=job_class.priority,
            max_attempts=job_class.max_attempts,
            run_at=computed_run_at,
            status="scheduled" if computed_run_at else "enqueued",
        )

        job_id = self.backend.enqueue(record)
        logger.info(
            "Enqueued %s (id=%s, queue=%s)",
            job_class.__name__,
            job_id,
            job_class.queue,
        )
        return job_id


def _resolve_run_at(delay: timedelta | None, run_at: datetime | None) -> datetime | None:
    """Compute run_at from delay or explicit time."""
    if delay is not None:
        return datetime.now(timezone.utc).replace(tzinfo=None) + delay
    return run_at


def get_client() -> Client:
    """Get the global client instance."""
    if _client is None:
        raise ConfigurationError(
            "CrazyJob client not initialized. " "Call set_client() or use a framework integration."
        )
    return _client


def set_client(client: Client) -> None:
    """Set the global client instance."""
    global _client
    _client = client
