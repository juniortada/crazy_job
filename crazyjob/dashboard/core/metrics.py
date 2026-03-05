"""Dashboard metrics — throughput, latency, error rate calculations."""
from __future__ import annotations

from typing import Any


class DashboardMetrics:
    """Compute real-time metrics from the jobs table."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend

    def throughput_per_minute(self, window_minutes: int = 5) -> float:
        """Average completed jobs per minute over the given window."""
        sql = """
            SELECT COUNT(*) as count FROM cj_jobs
            WHERE status = 'completed'
              AND completed_at >= NOW() - INTERVAL '%s minutes';
        """
        with self.backend._cursor() as cur:
            cur.execute(sql, (window_minutes,))
            count = cur.fetchone()["count"]
            return round(count / window_minutes, 2) if count > 0 else 0.0

    def average_latency_seconds(self, window_minutes: int = 60) -> float:
        """Average time from enqueue to completion, in seconds."""
        sql = """
            SELECT AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_latency
            FROM cj_jobs
            WHERE status = 'completed'
              AND completed_at >= NOW() - INTERVAL '%s minutes';
        """
        with self.backend._cursor() as cur:
            cur.execute(sql, (window_minutes,))
            row = cur.fetchone()
            return round(row["avg_latency"] or 0.0, 2)

    def error_rate_percent(self, window_minutes: int = 60) -> float:
        """Percentage of failed jobs in the given window."""
        sql = """
            SELECT
                COUNT(*) FILTER (WHERE status IN ('failed', 'dead')) as errors,
                COUNT(*) as total
            FROM cj_jobs
            WHERE updated_at >= NOW() - INTERVAL '%s minutes';
        """
        with self.backend._cursor() as cur:
            cur.execute(sql, (window_minutes,))
            row = cur.fetchone()
            if row["total"] == 0:
                return 0.0
            return round(row["errors"] / row["total"] * 100, 2)

    def queue_depths(self) -> dict[str, int]:
        """Number of enqueued jobs per queue."""
        sql = """
            SELECT queue, COUNT(*) as depth
            FROM cj_jobs
            WHERE status IN ('enqueued', 'retrying')
            GROUP BY queue
            ORDER BY queue;
        """
        with self.backend._cursor() as cur:
            cur.execute(sql)
            return {row["queue"]: row["depth"] for row in cur.fetchall()}
