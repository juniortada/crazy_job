"""Factory functions for creating backend-specific dashboard instances."""

from __future__ import annotations

from typing import Any

from crazyjob.dashboard.core.actions import DashboardActions
from crazyjob.dashboard.core.metrics import DashboardMetrics
from crazyjob.dashboard.core.queries import DashboardQueries


def _is_sqlite(backend: Any) -> bool:
    """Check if the backend is a SQLite driver without importing it."""
    return type(backend).__name__ == "SQLiteDriver"


def create_dashboard_queries(backend: Any) -> DashboardQueries:
    """Return the correct DashboardQueries for the given backend."""
    if _is_sqlite(backend):
        from crazyjob.dashboard.core.sqlite_queries import SQLiteDashboardQueries

        return SQLiteDashboardQueries(backend)
    return DashboardQueries(backend)


def create_dashboard_actions(backend: Any) -> DashboardActions:
    """Return the correct DashboardActions for the given backend."""
    if _is_sqlite(backend):
        from crazyjob.dashboard.core.sqlite_actions import SQLiteDashboardActions

        return SQLiteDashboardActions(backend)
    return DashboardActions(backend)


def create_dashboard_metrics(backend: Any) -> DashboardMetrics:
    """Return the correct DashboardMetrics for the given backend."""
    if _is_sqlite(backend):
        from crazyjob.dashboard.core.sqlite_metrics import SQLiteDashboardMetrics

        return SQLiteDashboardMetrics(backend)
    return DashboardMetrics(backend)
