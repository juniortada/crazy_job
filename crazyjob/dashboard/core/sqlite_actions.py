"""Dashboard actions — SQLite-compatible SQL."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from crazyjob.dashboard.core.actions import DashboardActions

logger = logging.getLogger(__name__)


class SQLiteDashboardActions(DashboardActions):
    """SQLite override of DashboardActions with compatible SQL syntax."""

    def resurrect(self, dead_letter_id: str) -> str:
        with self.backend._cursor() as cur:
            cur.execute(
                "SELECT * FROM cj_dead_letters WHERE id = ?;",
                (dead_letter_id,),
            )
            dead = cur.fetchone()
            if dead is None:
                raise ValueError(f"Dead letter {dead_letter_id} not found")

            original_raw = dead["original_job"]
            original = json.loads(original_raw) if isinstance(original_raw, str) else original_raw

            new_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO cj_jobs (id, queue, class_path, args, kwargs, status,
                                     priority, attempts, max_attempts,
                                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'enqueued', ?, 0, ?,
                        datetime('now'), datetime('now'));
                """,
                (
                    new_id,
                    original.get("queue", "default"),
                    original["class_path"],
                    json.dumps(original.get("args", [])),
                    json.dumps(original.get("kwargs", {})),
                    original.get("priority", 50),
                    original.get("max_attempts", 3),
                ),
            )

            cur.execute(
                "UPDATE cj_dead_letters SET resurrected_at = datetime('now') WHERE id = ?;",
                (dead_letter_id,),
            )

        logger.info("Resurrected dead letter %s as job %s", dead_letter_id, new_id)
        return new_id

    def bulk_resurrect(self) -> int:
        with self.backend._cursor() as cur:
            cur.execute("SELECT id FROM cj_dead_letters WHERE resurrected_at IS NULL;")
            dead_ids = [row["id"] for row in cur.fetchall()]

        count = 0
        for dead_id in dead_ids:
            try:
                self.resurrect(str(dead_id))
                count += 1
            except Exception:
                logger.exception("Failed to resurrect dead letter %s", dead_id)
        return count

    def cancel(self, job_id: str) -> None:
        with self.backend._cursor() as cur:
            cur.execute(
                "DELETE FROM cj_jobs WHERE id = ? AND status = 'enqueued';",
                (job_id,),
            )
        logger.info("Cancelled job %s", job_id)

    def pause_queue(self, queue: str) -> None:
        with self.backend._cursor() as cur:
            cur.execute(
                """
                INSERT OR IGNORE INTO cj_queue_pauses (queue, paused_at)
                VALUES (?, datetime('now'));
                """,
                (queue,),
            )
        logger.info("Paused queue '%s'", queue)

    def resume_queue(self, queue: str) -> None:
        with self.backend._cursor() as cur:
            cur.execute(
                "DELETE FROM cj_queue_pauses WHERE queue = ?;",
                (queue,),
            )
        logger.info("Resumed queue '%s'", queue)

    def clear_queue(self, queue: str) -> None:
        with self.backend._cursor() as cur:
            cur.execute(
                "DELETE FROM cj_jobs WHERE queue = ? AND status = 'enqueued';",
                (queue,),
            )
        logger.info("Cleared queue '%s'", queue)

    def trigger_schedule(self, schedule_id: str) -> str:
        with self.backend._cursor() as cur:
            cur.execute("SELECT * FROM cj_schedules WHERE id = ?;", (schedule_id,))
            schedule = cur.fetchone()
            if schedule is None:
                raise ValueError(f"Schedule {schedule_id} not found")

            args_raw = schedule["args"]
            kwargs_raw = schedule["kwargs"]

            new_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO cj_jobs (id, queue, class_path, args, kwargs, status,
                                     created_at, updated_at)
                VALUES (?, 'default', ?, ?, ?, 'enqueued',
                        datetime('now'), datetime('now'));
                """,
                (
                    new_id,
                    schedule["class_path"],
                    args_raw if isinstance(args_raw, str) else json.dumps(args_raw),
                    kwargs_raw if isinstance(kwargs_raw, str) else json.dumps(kwargs_raw),
                ),
            )
        logger.info("Triggered schedule %s → job %s", schedule_id, new_id)
        return new_id
