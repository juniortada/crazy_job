"""Dashboard query layer — SQLite-compatible SQL."""
from __future__ import annotations

import json
from typing import Any

from crazyjob.dashboard.core.queries import DashboardQueries


class SQLiteDashboardQueries(DashboardQueries):
    """SQLite override of DashboardQueries with compatible SQL syntax."""

    def overview_stats(self) -> dict:
        sql = """
            SELECT status, COUNT(*) as count
            FROM cj_jobs
            GROUP BY status;
        """
        with self.backend._cursor() as cur:
            cur.execute(sql)
            counts = {row["status"]: row["count"] for row in cur.fetchall()}

        sql_throughput = """
            SELECT COUNT(*) as count FROM cj_jobs
            WHERE status = 'completed'
              AND completed_at >= datetime('now', '-5 minutes');
        """
        with self.backend._cursor() as cur:
            cur.execute(sql_throughput)
            completed_5m = cur.fetchone()["count"]
            throughput = completed_5m / 5.0 if completed_5m > 0 else 0.0

        sql_error = """
            SELECT
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                COUNT(*) as total
            FROM cj_jobs
            WHERE updated_at >= datetime('now', '-1 hour');
        """
        with self.backend._cursor() as cur:
            cur.execute(sql_error)
            row = cur.fetchone()
            failed = row["failed"] or 0
            total = row["total"] or 0
            error_rate = (failed / total * 100) if total > 0 else 0.0

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
    ) -> list[dict]:
        offset = (page - 1) * per_page
        if queue:
            sql = """
                SELECT * FROM cj_jobs
                WHERE status = ? AND queue = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?;
            """
            params: tuple[Any, ...] = (status, queue, per_page, offset)
        else:
            sql = """
                SELECT * FROM cj_jobs
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?;
            """
            params = (status, per_page, offset)

        with self.backend._cursor() as cur:
            cur.execute(sql, params)
            return [{key: row[key] for key in row.keys()} for row in cur.fetchall()]

    def list_workers(self) -> list[dict]:
        sql = "SELECT * FROM cj_workers ORDER BY started_at DESC;"
        with self.backend._cursor() as cur:
            cur.execute(sql)
            rows = []
            for row in cur.fetchall():
                d = {key: row[key] for key in row.keys()}
                if isinstance(d.get("queues"), str):
                    d["queues"] = json.loads(d["queues"])
                rows.append(d)
            return rows

    def list_dead_letters(self, page: int = 1, per_page: int = 25) -> list[dict]:
        offset = (page - 1) * per_page
        sql = """
            SELECT * FROM cj_dead_letters
            ORDER BY killed_at DESC
            LIMIT ? OFFSET ?;
        """
        with self.backend._cursor() as cur:
            cur.execute(sql, (per_page, offset))
            rows = []
            for row in cur.fetchall():
                d = {key: row[key] for key in row.keys()}
                if isinstance(d.get("original_job"), str):
                    d["original_job"] = json.loads(d["original_job"])
                rows.append(d)
            return rows

    def list_schedules(self) -> list[dict]:
        sql = "SELECT * FROM cj_schedules ORDER BY name;"
        with self.backend._cursor() as cur:
            cur.execute(sql)
            return [{key: row[key] for key in row.keys()} for row in cur.fetchall()]
