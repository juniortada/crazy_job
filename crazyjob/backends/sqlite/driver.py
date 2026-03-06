"""SQLite backend driver using BEGIN IMMEDIATE for serialized job claiming."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from crazyjob.backends.base import BackendDriver
from crazyjob.core.job import DeadLetterRecord, JobRecord, WorkerRecord

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


class SQLiteDriver(BackendDriver):
    """SQLite implementation of BackendDriver.

    Uses WAL mode for concurrent reads and a threading.Lock to serialize writes.
    Suitable for development, testing, and single-machine deployments.
    """

    dashboard_variant = "sqlite"

    def __init__(self, database_path: str = ":memory:") -> None:
        self._database_path = database_path
        self._conn = sqlite3.connect(
            database_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.Lock()
        self._closed = False

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """Provide a cursor with auto-commit. Compatible with dashboard layer."""
        with self._lock:
            if self._closed:
                raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
            cursor = self._conn.cursor()
            try:
                yield cursor
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        """Close the SQLite connection. Safe to call from any thread."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self._conn.close()

    # ── Enqueue ──────────────────────────────────────────────────────────────

    def enqueue(self, job: JobRecord) -> str:
        sql = """
            INSERT INTO cj_jobs (id, queue, class_path, args, kwargs, status,
                                 priority, attempts, max_attempts, run_at,
                                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'));
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
                    job.run_at.isoformat() if job.run_at else None,
                ),
            )
            return job.id

    # ── Fetch (atomic claim with BEGIN IMMEDIATE) ─────────────────────────

    def fetch_next(self, queues: list[str], worker_id: str) -> JobRecord | None:
        """Atomically fetch and claim the next job.

        Uses BEGIN IMMEDIATE + threading.Lock to serialize writers.
        Increments attempts and sets started_at in the same transaction.
        """
        placeholders = ",".join("?" * len(queues))
        sql = (
            "SELECT id FROM cj_jobs"
            " WHERE status IN ('enqueued', 'retrying')"
            " AND (run_at IS NULL OR run_at <= datetime('now'))"
            f" AND queue IN ({placeholders})"  # nosec B608
            " ORDER BY priority ASC, created_at ASC"
            " LIMIT 1;"
        )
        with self._lock:
            if self._closed:
                return None
            cursor = self._conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute(sql, queues)
                row = cursor.fetchone()
                if row is None:
                    self._conn.commit()
                    return None

                job_id = row["id"]
                cursor.execute(
                    """
                    UPDATE cj_jobs
                    SET status = 'active',
                        worker_id = ?,
                        started_at = datetime('now'),
                        attempts = attempts + 1,
                        updated_at = datetime('now')
                    WHERE id = ?;
                """,
                    (worker_id, job_id),
                )
                cursor.execute("SELECT * FROM cj_jobs WHERE id = ?;", (job_id,))
                updated = cursor.fetchone()
                self._conn.commit()
                return self._row_to_job_record(dict(updated))
            except Exception:
                self._conn.rollback()
                raise

    # ── Mark completed ───────────────────────────────────────────────────────

    def mark_completed(self, job_id: str, result: dict[str, object]) -> None:
        sql = """
            UPDATE cj_jobs
            SET status = 'completed', completed_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?;
        """
        with self._cursor() as cur:
            cur.execute(sql, (job_id,))

    # ── Mark failed ──────────────────────────────────────────────────────────

    def mark_failed(self, job_id: str, error: str, retry_at: datetime | None = None) -> None:
        if retry_at is not None:
            sql = """
                UPDATE cj_jobs
                SET status = 'retrying', error = ?, failed_at = datetime('now'),
                    run_at = ?, updated_at = datetime('now')
                WHERE id = ?;
            """
            with self._cursor() as cur:
                cur.execute(sql, (error, retry_at.isoformat(), job_id))
        else:
            sql = """
                UPDATE cj_jobs
                SET status = 'failed', error = ?, failed_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ?;
            """
            with self._cursor() as cur:
                cur.execute(sql, (error, job_id))

    # ── Move to dead letters ─────────────────────────────────────────────────

    def move_to_dead(self, job_id: str, reason: str) -> None:
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("SELECT * FROM cj_jobs WHERE id = ?;", (job_id,))
                job_row = cursor.fetchone()
                if job_row is None:
                    return

                original_job = {key: job_row[key] for key in job_row.keys()}  # noqa: SIM118

                dead_id = str(uuid4())
                cursor.execute(
                    """
                    INSERT INTO cj_dead_letters (id, original_job, reason, killed_at)
                    VALUES (?, ?, ?, datetime('now'));
                    """,
                    (dead_id, json.dumps(original_job, default=str), reason),
                )

                cursor.execute(
                    """
                    UPDATE cj_jobs
                    SET status = 'dead', updated_at = datetime('now')
                    WHERE id = ?;
                    """,
                    (job_id,),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ── Worker registry ──────────────────────────────────────────────────────

    def register_worker(self, worker: WorkerRecord) -> None:
        sql = """
            INSERT INTO cj_workers (id, queues, concurrency, status,
                                    started_at, last_beat_at)
            VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT (id) DO UPDATE
            SET queues = excluded.queues,
                concurrency = excluded.concurrency,
                status = excluded.status,
                started_at = datetime('now'),
                last_beat_at = datetime('now');
        """
        with self._cursor() as cur:
            cur.execute(
                sql,
                (
                    worker.id,
                    json.dumps(worker.queues),
                    worker.concurrency,
                    worker.status,
                ),
            )

    def heartbeat(self, worker_id: str) -> None:
        sql = "UPDATE cj_workers SET last_beat_at = datetime('now') WHERE id = ?;"
        with self._cursor() as cur:
            cur.execute(sql, (worker_id,))

    def deregister_worker(self, worker_id: str) -> None:
        sql = "DELETE FROM cj_workers WHERE id = ?;"
        with self._cursor() as cur:
            cur.execute(sql, (worker_id,))

    # ── Queries ──────────────────────────────────────────────────────────────

    def get_job(self, job_id: str) -> JobRecord | None:
        sql = "SELECT * FROM cj_jobs WHERE id = ?;"
        with self._cursor() as cur:
            cur.execute(sql, (job_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_job_record(dict(row))

    def get_dead_letter(self, job_id: str) -> DeadLetterRecord | None:
        sql = """
            SELECT * FROM cj_dead_letters
            WHERE json_extract(original_job, '$.id') = ?
            ORDER BY killed_at DESC
            LIMIT 1;
        """
        with self._cursor() as cur:
            cur.execute(sql, (str(job_id),))
            row = cur.fetchone()
            if row is None:
                return None
            original = row["original_job"]
            return DeadLetterRecord(
                id=str(row["id"]),
                original_job=json.loads(original) if isinstance(original, str) else original,
                reason=row["reason"],
                killed_at=self._parse_datetime(row["killed_at"]) or datetime.now(timezone.utc).replace(tzinfo=None),
                resurrected_at=self._parse_datetime(row["resurrected_at"]),
            )

    # ── Dead worker detection helpers ────────────────────────────────────────

    def get_stale_workers(self, threshold_seconds: int) -> list[WorkerRecord]:
        """Find workers whose heartbeat is older than the threshold."""
        sql = """
            SELECT * FROM cj_workers
            WHERE last_beat_at < datetime('now', ? || ' seconds')
              AND status != 'stopped';
        """
        with self._cursor() as cur:
            cur.execute(sql, (f"-{threshold_seconds}",))
            return [self._row_to_worker_record(dict(row)) for row in cur.fetchall()]

    def get_active_jobs_for_worker(self, worker_id: str) -> list[JobRecord]:
        """Get all active jobs assigned to a specific worker."""
        sql = "SELECT * FROM cj_jobs WHERE worker_id = ? AND status = 'active';"
        with self._cursor() as cur:
            cur.execute(sql, (worker_id,))
            return [self._row_to_job_record(dict(row)) for row in cur.fetchall()]

    def reenqueue_job(self, job_id: str) -> None:
        """Re-enqueue a job (e.g., from a dead worker)."""
        sql = """
            UPDATE cj_jobs
            SET status = 'enqueued', worker_id = NULL, started_at = NULL,
                updated_at = datetime('now')
            WHERE id = ?;
        """
        with self._cursor() as cur:
            cur.execute(sql, (job_id,))

    def mark_worker_stopped(self, worker_id: str) -> None:
        """Mark a worker as stopped."""
        sql = "UPDATE cj_workers SET status = 'stopped' WHERE id = ?;"
        with self._cursor() as cur:
            cur.execute(sql, (worker_id,))

    # ── Scheduler helpers ────────────────────────────────────────────────────

    def fetch_due_schedules(self) -> list[dict[str, object]]:
        """Fetch schedules that are due to run."""
        sql = """
            SELECT * FROM cj_schedules
            WHERE enabled = 1
              AND (next_run_at IS NULL OR next_run_at <= datetime('now'));
        """
        with self._cursor() as cur:
            cur.execute(sql)
            return [{key: row[key] for key in row.keys()} for row in cur.fetchall()]  # noqa: SIM118

    def update_schedule_timestamps(
        self, schedule_id: str, last_run_at: datetime, next_run_at: datetime
    ) -> None:
        """Update a schedule's run timestamps after firing."""
        sql = """
            UPDATE cj_schedules
            SET last_run_at = ?, next_run_at = ?
            WHERE id = ?;
        """
        with self._cursor() as cur:
            cur.execute(sql, (last_run_at.isoformat(), next_run_at.isoformat(), schedule_id))

    # ── Row mappers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        """Parse an ISO 8601 datetime string from SQLite."""
        if not isinstance(value, str):
            return None
        # Handle both 'YYYY-MM-DDTHH:MM:SS' and 'YYYY-MM-DD HH:MM:SS' formats
        return datetime.fromisoformat(value)

    @staticmethod
    def _row_to_job_record(row: dict[str, object]) -> JobRecord:
        args_raw = row["args"]
        kwargs_raw = row["kwargs"]
        parsed = {
            "id": str(row["id"]),
            "queue": row["queue"],
            "class_path": row["class_path"],
            "args": json.loads(str(args_raw)) if isinstance(args_raw, str) else args_raw,
            "kwargs": (json.loads(str(kwargs_raw)) if isinstance(kwargs_raw, str) else kwargs_raw),
            "status": row["status"],
            "priority": row["priority"],
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "run_at": SQLiteDriver._parse_datetime(row.get("run_at")),
            "started_at": SQLiteDriver._parse_datetime(row.get("started_at")),
            "completed_at": SQLiteDriver._parse_datetime(row.get("completed_at")),
            "failed_at": SQLiteDriver._parse_datetime(row.get("failed_at")),
            "error": row.get("error"),
            "worker_id": row.get("worker_id"),
            "created_at": (SQLiteDriver._parse_datetime(row["created_at"]) or datetime.now(timezone.utc).replace(tzinfo=None)),
            "updated_at": (SQLiteDriver._parse_datetime(row["updated_at"]) or datetime.now(timezone.utc).replace(tzinfo=None)),
        }
        return JobRecord(**parsed)  # type: ignore[arg-type]

    @staticmethod
    def _row_to_worker_record(row: dict[str, object]) -> WorkerRecord:
        queues_raw = row["queues"]
        queues = json.loads(str(queues_raw)) if isinstance(queues_raw, str) else queues_raw
        parsed = {
            "id": row["id"],
            "queues": queues,
            "concurrency": row["concurrency"],
            "status": row["status"],
            "current_job_id": row.get("current_job_id"),
            "started_at": (SQLiteDriver._parse_datetime(row["started_at"]) or datetime.now(timezone.utc).replace(tzinfo=None)),
            "last_beat_at": (
                SQLiteDriver._parse_datetime(row["last_beat_at"]) or datetime.now(timezone.utc).replace(tzinfo=None)
            ),
        }
        return WorkerRecord(**parsed)  # type: ignore[arg-type]
