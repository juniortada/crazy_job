"""Dashboard query layer — pure Python, framework-agnostic."""

from __future__ import annotations

from typing import Any


class DashboardQueries:
    """All dashboard read operations. No HTTP, no framework."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend

    def overview_stats(self) -> dict[str, object]:
        """Returns counts per status, throughput (jobs/min), error rate."""
        sql = """
            SELECT status, COUNT(*) as count
            FROM cj_jobs
            GROUP BY status;
        """
        with self.backend._cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            counts = {row["status"]: row["count"] for row in rows}

        # Throughput: completed jobs in last 5 minutes
        sql_throughput = """
            SELECT COUNT(*) as count FROM cj_jobs
            WHERE status = 'completed'
              AND completed_at >= NOW() - INTERVAL '5 minutes';
        """
        with self.backend._cursor() as cur:
            cur.execute(sql_throughput)
            completed_5m = cur.fetchone()["count"]
            throughput = completed_5m / 5.0 if completed_5m > 0 else 0.0

        # Error rate: failed / total in last hour
        sql_error = """
            SELECT
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COUNT(*) as total
            FROM cj_jobs
            WHERE updated_at >= NOW() - INTERVAL '1 hour';
        """
        with self.backend._cursor() as cur:
            cur.execute(sql_error)
            row = cur.fetchone()
            error_rate = (row["failed"] / row["total"] * 100) if row["total"] > 0 else 0.0

        return {
            "counts": counts,
            "throughput": round(throughput, 2),
            "error_rate": round(error_rate, 2),
        }

    def list_jobs(
        self,
        status: str,
        queue: str | None = None,
        page: int = 1,
        per_page: int = 25,
    ) -> list[dict[str, object]]:
        """List jobs filtered by status, with pagination."""
        offset = (page - 1) * per_page
        if queue:
            sql = """
                SELECT * FROM cj_jobs
                WHERE status = %s AND queue = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s;
            """
            params = (status, queue, per_page, offset)
        else:
            sql = """
                SELECT * FROM cj_jobs
                WHERE status = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s;
            """
            params = (status, per_page, offset)  # type: ignore[assignment]

        with self.backend._cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def list_workers(self) -> list[dict[str, object]]:
        """List all registered workers."""
        sql = "SELECT * FROM cj_workers ORDER BY started_at DESC;"
        with self.backend._cursor() as cur:
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]

    def list_dead_letters(self, page: int = 1, per_page: int = 25) -> list[dict[str, object]]:
        """List dead letters with pagination."""
        offset = (page - 1) * per_page
        sql = """
            SELECT * FROM cj_dead_letters
            ORDER BY killed_at DESC
            LIMIT %s OFFSET %s;
        """
        with self.backend._cursor() as cur:
            cur.execute(sql, (per_page, offset))
            return [dict(row) for row in cur.fetchall()]

    def list_schedules(self) -> list[dict[str, object]]:
        """List all cron schedules."""
        sql = "SELECT * FROM cj_schedules ORDER BY name;"
        with self.backend._cursor() as cur:
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]
