"""PostgreSQL backend driver using psycopg (v3) with SELECT ... FOR UPDATE SKIP LOCKED."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any

import psycopg
import psycopg.rows
from psycopg_pool import ConnectionPool

from crazyjob.backends.base import BackendDriver
from crazyjob.core.job import DeadLetterRecord, JobRecord, WorkerRecord

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


class PostgreSQLDriver(BackendDriver):
    """PostgreSQL implementation of BackendDriver.

    Uses psycopg_pool.ConnectionPool and SKIP LOCKED for safe concurrent job
    consumption across multiple workers.
    """

    dashboard_variant = "postgresql"

    def __init__(self, dsn: str, min_conn: int = 1, max_conn: int = 10) -> None:
        self._pool: ConnectionPool[Any] = ConnectionPool(
            conninfo=dsn,
            min_size=min_conn,
            max_size=max_conn,
            open=True,
        )

    @contextmanager
    def _conn(self) -> Generator[psycopg.Connection[Any], None, None]:
        """Yield a connection from the pool; commits on success, rolls back on error."""
        with self._pool.connection() as conn:
            yield conn

    @contextmanager
    def _cursor(self) -> Generator[psycopg.Cursor[dict[str, Any]], None, None]:
        """Yield a dict-row cursor backed by a pooled connection."""
        with self._conn() as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            yield cur

    def close(self) -> None:
        """Close all connections in the pool."""
        self._pool.close()

    # ── Enqueue ──────────────────────────────────────────────────────────────

    def enqueue(self, job: JobRecord) -> str:
        sql = """
            INSERT INTO cj_jobs (id, queue, class_path, args, kwargs, status,
                                 priority, attempts, max_attempts, run_at,
                                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            RETURNING id;
        """
        with self._cursor() as cur:
            cur.execute(
                sql,
                (
                    job.id,
                    job.queue,
                    job.class_path,
                    json.dumps(job.args),
                    json.dumps(job.kwargs),
                    job.status,
                    job.priority,
                    job.attempts,
                    job.max_attempts,
                    job.run_at,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            return str(row["id"])

    # ── Fetch (atomic claim with SKIP LOCKED) ────────────────────────────────

    def fetch_next(self, queues: list[str], worker_id: str) -> JobRecord | None:
        """Atomically fetch, lock, claim, and increment attempts for the next job.

        This is a single CTE that does SELECT FOR UPDATE SKIP LOCKED + UPDATE
        RETURNING in one statement. All four state changes (status, worker_id,
        started_at, attempts) happen before any user code runs.
        """
        sql = """
            WITH next_job AS (
                SELECT id FROM cj_jobs
                WHERE status IN ('enqueued', 'retrying')
                  AND (run_at IS NULL OR run_at <= NOW())
                  AND queue = ANY(%s)
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE cj_jobs
            SET
                status     = 'active',
                worker_id  = %s,
                started_at = NOW(),
                attempts   = attempts + 1,
                updated_at = NOW()
            FROM next_job
            WHERE cj_jobs.id = next_job.id
            RETURNING cj_jobs.*;
        """
        with self._cursor() as cur:
            cur.execute(sql, (queues, worker_id))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_job_record(row)

    # ── Mark completed ───────────────────────────────────────────────────────

    def mark_completed(self, job_id: str, result: dict[str, object]) -> None:
        sql = """
            UPDATE cj_jobs
            SET status = 'completed', completed_at = NOW(), updated_at = NOW()
            WHERE id = %s;
        """
        with self._cursor() as cur:
            cur.execute(sql, (job_id,))

    # ── Mark failed ──────────────────────────────────────────────────────────

    def mark_failed(self, job_id: str, error: str, retry_at: datetime | None = None) -> None:
        if retry_at is not None:
            sql = """
                UPDATE cj_jobs
                SET status = 'retrying', error = %s, failed_at = NOW(),
                    run_at = %s, updated_at = NOW()
                WHERE id = %s;
            """
            with self._cursor() as cur:
                cur.execute(sql, (error, retry_at, job_id))
        else:
            sql = """
                UPDATE cj_jobs
                SET status = 'failed', error = %s, failed_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s;
            """
            with self._cursor() as cur:
                cur.execute(sql, (error, job_id))

    # ── Move to dead letters ─────────────────────────────────────────────────

    def move_to_dead(self, job_id: str, reason: str) -> None:
        with self._conn() as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            # Snapshot the job as JSONB
            cur.execute("SELECT * FROM cj_jobs WHERE id = %s;", (job_id,))
            job_row = cur.fetchone()
            if job_row is None:
                return

            original_job = {
                k: (v.isoformat() if isinstance(v, datetime) else v)
                for k, v in job_row.items()
            }

            cur.execute(
                """
                INSERT INTO cj_dead_letters (original_job, reason, killed_at)
                VALUES (%s, %s, NOW());
                """,
                (json.dumps(original_job, default=str), reason),
            )

            cur.execute(
                """
                UPDATE cj_jobs
                SET status = 'dead', updated_at = NOW()
                WHERE id = %s;
                """,
                (job_id,),
            )

    # ── Worker registry ──────────────────────────────────────────────────────

    def register_worker(self, worker: WorkerRecord) -> None:
        sql = """
            INSERT INTO cj_workers (id, queues, concurrency, status, started_at, last_beat_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE
            SET queues = EXCLUDED.queues,
                concurrency = EXCLUDED.concurrency,
                status = EXCLUDED.status,
                started_at = NOW(),
                last_beat_at = NOW();
        """
        with self._cursor() as cur:
            cur.execute(sql, (worker.id, worker.queues, worker.concurrency, worker.status))

    def heartbeat(self, worker_id: str) -> None:
        sql = "UPDATE cj_workers SET last_beat_at = NOW() WHERE id = %s;"
        with self._cursor() as cur:
            cur.execute(sql, (worker_id,))

    def deregister_worker(self, worker_id: str) -> None:
        sql = "DELETE FROM cj_workers WHERE id = %s;"
        with self._cursor() as cur:
            cur.execute(sql, (worker_id,))

    # ── Queries ──────────────────────────────────────────────────────────────

    def get_job(self, job_id: str) -> JobRecord | None:
        sql = "SELECT * FROM cj_jobs WHERE id = %s;"
        with self._cursor() as cur:
            cur.execute(sql, (job_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_job_record(row)

    def get_dead_letter(self, job_id: str) -> DeadLetterRecord | None:
        sql = """
            SELECT * FROM cj_dead_letters
            WHERE original_job->>'id' = %s
            ORDER BY killed_at DESC
            LIMIT 1;
        """
        with self._cursor() as cur:
            cur.execute(sql, (str(job_id),))
            row = cur.fetchone()
            if row is None:
                return None
            return DeadLetterRecord(
                id=str(row["id"]),
                original_job=(
                    row["original_job"]
                    if isinstance(row["original_job"], dict)
                    else json.loads(row["original_job"])
                ),
                reason=row["reason"],
                killed_at=row["killed_at"],
                resurrected_at=row.get("resurrected_at"),
            )

    # ── Dead worker detection helpers ────────────────────────────────────────

    def get_stale_workers(self, threshold_seconds: int) -> list[WorkerRecord]:
        """Find workers whose heartbeat is older than the threshold."""
        sql = """
            SELECT * FROM cj_workers
            WHERE last_beat_at < NOW() - make_interval(secs => %s)
              AND status != 'stopped';
        """
        with self._cursor() as cur:
            cur.execute(sql, (threshold_seconds,))
            return [self._row_to_worker_record(row) for row in cur.fetchall()]

    def get_active_jobs_for_worker(self, worker_id: str) -> list[JobRecord]:
        """Get all active jobs assigned to a specific worker."""
        sql = "SELECT * FROM cj_jobs WHERE worker_id = %s AND status = 'active';"
        with self._cursor() as cur:
            cur.execute(sql, (worker_id,))
            return [self._row_to_job_record(row) for row in cur.fetchall()]

    def reenqueue_job(self, job_id: str) -> None:
        """Re-enqueue a job (e.g., from a dead worker)."""
        sql = """
            UPDATE cj_jobs
            SET status = 'enqueued', worker_id = NULL, started_at = NULL,
                updated_at = NOW()
            WHERE id = %s;
        """
        with self._cursor() as cur:
            cur.execute(sql, (job_id,))

    def mark_worker_stopped(self, worker_id: str) -> None:
        """Mark a worker as stopped."""
        sql = "UPDATE cj_workers SET status = 'stopped' WHERE id = %s;"
        with self._cursor() as cur:
            cur.execute(sql, (worker_id,))

    # ── Scheduler helpers ────────────────────────────────────────────────────

    def fetch_due_schedules(self) -> list[dict[str, object]]:
        """Fetch schedules that are due to run, using SKIP LOCKED."""
        sql = """
            SELECT * FROM cj_schedules
            WHERE enabled = TRUE
              AND (next_run_at IS NULL OR next_run_at <= NOW())
            FOR UPDATE SKIP LOCKED;
        """
        with self._cursor() as cur:
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]

    def update_schedule_timestamps(
        self, schedule_id: str, last_run_at: datetime, next_run_at: datetime
    ) -> None:
        """Update a schedule's run timestamps after firing."""
        sql = """
            UPDATE cj_schedules
            SET last_run_at = %s, next_run_at = %s
            WHERE id = %s;
        """
        with self._cursor() as cur:
            cur.execute(sql, (last_run_at, next_run_at, schedule_id))

    # ── Row mappers ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_job_record(row: dict[str, Any]) -> JobRecord:
        args_raw = row["args"]
        kwargs_raw = row["kwargs"]
        parsed = {
            "id": str(row["id"]),
            "queue": row["queue"],
            "class_path": row["class_path"],
            "args": args_raw if isinstance(args_raw, list) else json.loads(str(args_raw)),
            "kwargs": (kwargs_raw if isinstance(kwargs_raw, dict) else json.loads(str(kwargs_raw))),
            "status": row["status"],
            "priority": row["priority"],
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "run_at": row.get("run_at"),
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
            "failed_at": row.get("failed_at"),
            "error": row.get("error"),
            "worker_id": row.get("worker_id"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        return JobRecord(**parsed)  # type: ignore[arg-type]

    @staticmethod
    def _row_to_worker_record(row: dict[str, Any]) -> WorkerRecord:
        parsed = {
            "id": row["id"],
            "queues": row["queues"],
            "concurrency": row["concurrency"],
            "status": row["status"],
            "current_job_id": (str(row["current_job_id"]) if row.get("current_job_id") else None),
            "started_at": row["started_at"],
            "last_beat_at": row["last_beat_at"],
        }
        return WorkerRecord(**parsed)  # type: ignore[arg-type]
