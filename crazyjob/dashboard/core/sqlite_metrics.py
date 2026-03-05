"""Dashboard metrics — SQLite-compatible SQL."""

from __future__ import annotations

from crazyjob.dashboard.core.metrics import DashboardMetrics


class SQLiteDashboardMetrics(DashboardMetrics):
    """SQLite override of DashboardMetrics with compatible SQL syntax."""

    def throughput_per_minute(self, window_minutes: int = 5) -> float:
        sql = """
            SELECT COUNT(*) as count FROM cj_jobs
            WHERE status = 'completed'
              AND completed_at >= datetime('now', ? || ' minutes');
        """
        with self.backend._cursor() as cur:
            cur.execute(sql, (f"-{window_minutes}",))
            count = cur.fetchone()["count"]
            return round(count / window_minutes, 2) if count > 0 else 0.0

    def average_latency_seconds(self, window_minutes: int = 60) -> float:
        sql = """
            SELECT AVG(
                (julianday(completed_at) - julianday(created_at)) * 86400
            ) as avg_latency
            FROM cj_jobs
            WHERE status = 'completed'
              AND completed_at >= datetime('now', ? || ' minutes');
        """
        with self.backend._cursor() as cur:
            cur.execute(sql, (f"-{window_minutes}",))
            row = cur.fetchone()
            return round(row["avg_latency"] or 0.0, 2)

    def error_rate_percent(self, window_minutes: int = 60) -> float:
        sql = """
            SELECT
                SUM(CASE WHEN status IN ('failed', 'dead') THEN 1 ELSE 0 END) as errors,
                COUNT(*) as total
            FROM cj_jobs
            WHERE updated_at >= datetime('now', ? || ' minutes');
        """
        with self.backend._cursor() as cur:
            cur.execute(sql, (f"-{window_minutes}",))
            row = cur.fetchone()
            errors = row["errors"] or 0
            total = row["total"] or 0
            if total == 0:
                return 0.0
            return round(errors / total * 100, 2)

    def queue_depths(self) -> dict[str, int]:
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
