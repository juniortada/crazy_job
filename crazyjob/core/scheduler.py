"""Cron job scheduler for CrazyJob."""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime
from typing import Any

from croniter import croniter

from crazyjob.backends.base import BackendDriver
from crazyjob.core.client import Client
from crazyjob.core.job import Job, JobRecord

logger = logging.getLogger(__name__)


class Scheduler:
    """Reads cj_schedules and enqueues jobs when their cron expression fires.

    Uses SELECT ... FOR UPDATE SKIP LOCKED on the schedules table, so running
    multiple scheduler processes is safe.
    """

    def __init__(
        self,
        backend: BackendDriver,
        poll_interval: float = 10.0,
    ) -> None:
        self.backend = backend
        self._poll_interval = poll_interval
        self._running = False

    def run(self) -> None:
        """Start the scheduler loop. Blocks until shutdown."""
        self._running = True
        self._install_signal_handlers()
        logger.info("Scheduler started")

        while self._running:
            try:
                self._tick()
            except Exception:
                logger.exception("Scheduler tick failed")
            time.sleep(self._poll_interval)

        logger.info("Scheduler stopped")

    def shutdown(self) -> None:
        """Signal the scheduler to stop."""
        self._running = False

    def _tick(self) -> None:
        """Check for due schedules and enqueue their jobs."""
        due_schedules = self.backend.fetch_due_schedules()
        for schedule in due_schedules:
            self._fire_schedule(schedule)

    def _fire_schedule(self, schedule: dict) -> None:
        """Enqueue the job for a due schedule and update timestamps."""
        now = datetime.utcnow()

        record = JobRecord(
            class_path=schedule["class_path"],
            args=schedule.get("args", []),
            kwargs=schedule.get("kwargs", {}),
        )
        job_id = self.backend.enqueue(record)

        # Compute next run time
        cron = croniter(schedule["cron"], now)
        next_run = cron.get_next(datetime)

        self.backend.update_schedule_timestamps(
            schedule_id=str(schedule["id"]),
            last_run_at=now,
            next_run_at=next_run,
        )

        logger.info(
            "Fired schedule '%s' → job %s (next at %s)",
            schedule["name"],
            job_id,
            next_run,
        )

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, frame: Any) -> None:
        logger.info("Scheduler received signal %d, shutting down", signum)
        self.shutdown()


def schedule(cron: str, name: str) -> Any:
    """Decorator to register a Job subclass as a scheduled cron job.

    Usage::

        @schedule(cron="0 9 * * 1-5", name="daily_report")
        class DailyReportJob(Job):
            def perform(self):
                ...
    """

    def decorator(cls: type[Job]) -> type[Job]:
        cls._crazyjob_schedule_cron = cron  # type: ignore[attr-defined]
        cls._crazyjob_schedule_name = name  # type: ignore[attr-defined]
        return cls

    return decorator
