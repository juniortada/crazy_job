"""Worker engine — fetch loop, thread pool, heartbeat, graceful shutdown.

SOLID design notes:
- SRP: JobExecutor handles a single job's full execution lifecycle (load →
  run → handle outcome). Worker is an orchestrator: threads, signals,
  heartbeat, dead worker detection, registration.
- ISP: Worker is typed against WorkerBackend (JobStore + WorkerRegistry),
  not the full BackendDriver interface.
"""

from __future__ import annotations

import importlib
import logging
import os
import signal
import threading
import traceback
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from crazyjob.core.exceptions import Retry
from crazyjob.core.job import Job, JobRecord, WorkerRecord
from crazyjob.core.middleware import MiddlewarePipeline
from crazyjob.core.retry import get_backoff_policy

if TYPE_CHECKING:
    import types
    from collections.abc import Callable

    from crazyjob.backends.base import WorkerBackend

logger = logging.getLogger(__name__)


class JobExecutor:
    """Executes a single job: load class → run with middleware → handle outcome.

    SRP: this class has one responsibility. It knows nothing about threads,
    heartbeats, or worker registration.
    """

    def __init__(
        self,
        backend: WorkerBackend,
        pipeline: MiddlewarePipeline,
        context_wrapper: Callable[[Callable[[], object]], Callable[[], object]] | None = None,
    ) -> None:
        self._backend = backend
        self._pipeline = pipeline
        self._context_wrapper = context_wrapper

    def execute(self, job: JobRecord) -> None:
        """Run the job's perform() method with middleware wrapping."""
        instance: Job | None = None
        try:
            instance = self._load_job_class(job)
            perform_fn = self._build_perform_fn(instance, job)
            self._pipeline.run(job, perform_fn)
            self._backend.mark_completed(job.id, result={})
            logger.info("Job %s (%s) completed", job.id, job.class_path)

        except Retry as e:
            retry_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=e.in_seconds or 0)
            self._backend.mark_failed(job.id, error=str(e), retry_at=retry_at)
            logger.info("Job %s (%s) retry requested: %s", job.id, job.class_path, e)

        except Exception:
            self._handle_failure(job, instance)

    def _build_perform_fn(
        self, instance: Job, job: JobRecord
    ) -> Callable[[], object]:
        def perform_fn() -> object:
            instance.perform(*job.args, **job.kwargs)
            return None

        if self._context_wrapper:
            return self._context_wrapper(perform_fn)
        return perform_fn

    def _handle_failure(self, job: JobRecord, instance: Job | None) -> None:
        error_text = traceback.format_exc()
        if job.attempts >= job.max_attempts:
            # This was the last allowed attempt — send to dead letters
            self._backend.move_to_dead(job.id, reason=error_text)
            logger.warning(
                "Job %s (%s) moved to dead letters after %d attempts",
                job.id,
                job.class_path,
                job.attempts,
            )
        else:
            # Still have attempts left — schedule retry with backoff
            policy = get_backoff_policy(
                type(instance).retry_backoff if instance is not None else "exponential"
            )
            retry_at = datetime.now(timezone.utc).replace(tzinfo=None) + policy.delay_for(job.attempts)
            self._backend.mark_failed(job.id, error=error_text, retry_at=retry_at)
            logger.info(
                "Job %s (%s) failed (attempt %d/%d), retrying at %s",
                job.id,
                job.class_path,
                job.attempts,
                job.max_attempts,
                retry_at,
            )

    @staticmethod
    def _load_job_class(job: JobRecord) -> Job:
        """Dynamically import and instantiate the job class from its class_path."""
        module_path, class_name = job.class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls()  # type: ignore[no-any-return]


class Worker:
    """CrazyJob worker process — orchestrator only.

    Runs N fetch-loop threads + 1 heartbeat thread + 1 dead-detection thread.
    Delegates job execution to JobExecutor. Handles graceful shutdown on
    SIGTERM/SIGINT.

    SRP: this class orchestrates threads and lifecycle. It does not contain
    any job execution logic.
    ISP: typed against WorkerBackend (JobStore + WorkerRegistry) rather than
    the full BackendDriver.
    """

    def __init__(
        self,
        backend: WorkerBackend,
        queues: list[str],
        concurrency: int = 5,
        poll_interval: float = 1.0,
        shutdown_timeout: int = 30,
        heartbeat_interval: int = 10,
        dead_worker_threshold: int = 60,
        middleware_pipeline: MiddlewarePipeline | None = None,
        context_wrapper: Callable[[Callable[[], object]], Callable[[], object]] | None = None,
    ) -> None:
        self.backend = backend
        self._queues = queues
        self._concurrency = concurrency
        self._poll_interval = poll_interval
        self._shutdown_timeout = shutdown_timeout
        self._heartbeat_interval = heartbeat_interval
        self._dead_worker_threshold = dead_worker_threshold
        self._executor = JobExecutor(
            backend=backend,
            pipeline=middleware_pipeline or MiddlewarePipeline(),
            context_wrapper=context_wrapper,
        )
        self._running = False
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._worker_id = f"{os.uname().nodename}:{os.getpid()}"

    @property
    def id(self) -> str:
        return self._worker_id

    def run(self, max_jobs: int | None = None) -> None:
        """Start the worker. Blocks until shutdown."""
        self._running = True
        self._register()
        self._install_signal_handlers()

        # Start heartbeat thread
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="cj-heartbeat"
        )
        heartbeat_thread.start()

        # Start dead worker detection thread
        dead_detect_thread = threading.Thread(
            target=self._dead_worker_detection_loop, daemon=True, name="cj-dead-detect"
        )
        dead_detect_thread.start()

        # Start fetch-loop threads
        for i in range(self._concurrency):
            t = threading.Thread(
                target=self._run_loop,
                args=(max_jobs,),
                name=f"cj-worker-{i}",
                daemon=True,
            )
            self._threads.append(t)
            t.start()

        logger.info(
            "Worker %s started (queues=%s, concurrency=%d)",
            self._worker_id,
            self._queues,
            self._concurrency,
        )

        # Wait for all fetch threads to finish (bounded by shutdown_timeout)
        for t in self._threads:
            t.join(timeout=self._shutdown_timeout)

        # Signal auxiliary threads to wake up and exit, then wait for them
        self._running = False
        self._stop_event.set()
        heartbeat_thread.join(timeout=2)
        dead_detect_thread.join(timeout=2)

        try:
            self._deregister()
        except Exception:
            logger.debug("Worker deregister failed (backend may be closed during shutdown)")
        logger.info("Worker %s stopped", self._worker_id)

    def shutdown(self) -> None:
        """Signal the worker to stop gracefully."""
        logger.info("Worker %s shutting down...", self._worker_id)
        self._running = False
        self._stop_event.set()

    # ── Fetch loop (runs per thread) ─────────────────────────────────────────

    def _run_loop(self, max_jobs: int | None = None) -> None:
        jobs_processed = 0
        while self._running:
            if max_jobs is not None and jobs_processed >= max_jobs:
                break

            job = self.backend.fetch_next(self._queues, self._worker_id)

            if job is None:
                self._stop_event.wait(timeout=self._poll_interval)
                continue

            # At this point, job.attempts has ALREADY been incremented by fetch_next.
            # If we're at or over the limit, kill immediately — don't run user code.
            if job.attempts > job.max_attempts:
                self.backend.move_to_dead(
                    job.id,
                    reason=f"Exceeded max_attempts ({job.max_attempts})",
                )
                jobs_processed += 1
                continue

            try:
                self._executor.execute(job)
            except Exception:
                if not self._running:
                    break
                logger.exception("Unexpected error during job execution")
            jobs_processed += 1

    # ── Heartbeat ────────────────────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                self.backend.heartbeat(self._worker_id)
            except Exception:
                if not self._running:
                    break
                logger.exception("Heartbeat failed for worker %s", self._worker_id)
            self._stop_event.wait(timeout=self._heartbeat_interval)

    # ── Dead worker detection ────────────────────────────────────────────────

    def _dead_worker_detection_loop(self) -> None:
        while self._running:
            try:
                self._detect_dead_workers()
            except Exception:
                if not self._running:
                    break
                logger.exception("Dead worker detection failed")
            self._stop_event.wait(timeout=self._dead_worker_threshold)

    def _detect_dead_workers(self) -> None:
        """Find stale workers and re-enqueue their active jobs."""
        stale_workers = self.backend.get_stale_workers(self._dead_worker_threshold)
        for worker in stale_workers:
            logger.warning("Detected dead worker: %s", worker.id)
            active_jobs = self.backend.get_active_jobs_for_worker(worker.id)
            for job in active_jobs:
                if job.attempts >= job.max_attempts:
                    self.backend.move_to_dead(
                        job.id, reason=f"Worker {worker.id} died, max attempts reached"
                    )
                else:
                    self.backend.reenqueue_job(job.id)
                    logger.info("Re-enqueued job %s from dead worker %s", job.id, worker.id)
            self.backend.mark_worker_stopped(worker.id)

    # ── Worker registration ──────────────────────────────────────────────────

    def _register(self) -> None:
        record = WorkerRecord(
            id=self._worker_id,
            queues=self._queues,
            concurrency=self._concurrency,
            status="idle",
        )
        self.backend.register_worker(record)

    def _deregister(self) -> None:
        self.backend.deregister_worker(self._worker_id)

    # ── Signal handlers ──────────────────────────────────────────────────────

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, frame: types.FrameType | None) -> None:
        logger.info("Received signal %d, initiating graceful shutdown", signum)
        self.shutdown()
