"""Dashboard actions — resurrect, cancel, pause, clear, etc."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class DashboardActions:
    """All dashboard write operations. No HTTP, no framework."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend

    def resurrect(self, dead_letter_id: str) -> str:
        """Re-enqueue a dead job. Returns new job ID."""
        with self.backend._cursor() as cur:
            cur.execute(
                "SELECT * FROM cj_dead_letters WHERE id = %s;",
                (dead_letter_id,),
            )
            dead = cur.fetchone()
            if dead is None:
                raise ValueError(f"Dead letter {dead_letter_id} not found")

            original = (
                dead["original_job"]
                if isinstance(dead["original_job"], dict)
                else json.loads(dead["original_job"])
            )

            new_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO cj_jobs (id, queue, class_path, args, kwargs, status,
                                     priority, attempts, max_attempts, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'enqueued', %s, 0, %s, NOW(), NOW())
                RETURNING id;
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
                "UPDATE cj_dead_letters SET resurrected_at = NOW() WHERE id = %s;",
                (dead_letter_id,),
            )

        logger.info("Resurrected dead letter %s as job %s", dead_letter_id, new_id)
        return new_id

    def bulk_resurrect(self) -> int:
        """Resurrect all dead letters. Returns count."""
        with self.backend._cursor() as cur:
            cur.execute(
                "SELECT id FROM cj_dead_letters WHERE resurrected_at IS NULL;"
            )
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
        """Remove an enqueued job before it is picked up."""
        with self.backend._cursor() as cur:
            cur.execute(
                """
                DELETE FROM cj_jobs
                WHERE id = %s AND status = 'enqueued';
                """,
                (job_id,),
            )
        logger.info("Cancelled job %s", job_id)

    def pause_queue(self, queue: str) -> None:
        """Pause a queue (jobs won't be picked up)."""
        with self.backend._cursor() as cur:
            cur.execute(
                """
                INSERT INTO cj_queue_pauses (queue, paused_at)
                VALUES (%s, NOW())
                ON CONFLICT (queue) DO NOTHING;
                """,
                (queue,),
            )
        logger.info("Paused queue '%s'", queue)

    def resume_queue(self, queue: str) -> None:
        """Resume a paused queue."""
        with self.backend._cursor() as cur:
            cur.execute(
                "DELETE FROM cj_queue_pauses WHERE queue = %s;",
                (queue,),
            )
        logger.info("Resumed queue '%s'", queue)

    def clear_queue(self, queue: str) -> None:
        """Clear all enqueued jobs in a queue."""
        with self.backend._cursor() as cur:
            cur.execute(
                "DELETE FROM cj_jobs WHERE queue = %s AND status = 'enqueued';",
                (queue,),
            )
        logger.info("Cleared queue '%s'", queue)

    def trigger_schedule(self, schedule_id: str) -> str:
        """Manually trigger a schedule. Returns new job ID."""
        with self.backend._cursor() as cur:
            cur.execute("SELECT * FROM cj_schedules WHERE id = %s;", (schedule_id,))
            schedule = cur.fetchone()
            if schedule is None:
                raise ValueError(f"Schedule {schedule_id} not found")

            new_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO cj_jobs (id, queue, class_path, args, kwargs, status,
                                     created_at, updated_at)
                VALUES (%s, 'default', %s, %s, %s, 'enqueued', NOW(), NOW())
                RETURNING id;
                """,
                (
                    new_id,
                    schedule["class_path"],
                    json.dumps(schedule.get("args", [])),
                    json.dumps(schedule.get("kwargs", {})),
                ),
            )
        logger.info("Triggered schedule %s → job %s", schedule_id, new_id)
        return new_id
