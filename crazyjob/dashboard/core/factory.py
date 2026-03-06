"""Factory functions for creating backend-specific dashboard instances.

OCP: New backends declare their own dashboard_variant — this factory never
needs to be modified to support new drivers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crazyjob.dashboard.core.actions import DashboardActions
from crazyjob.dashboard.core.metrics import DashboardMetrics
from crazyjob.dashboard.core.queries import DashboardQueries

if TYPE_CHECKING:
    from crazyjob.backends.base import BackendDriver


def create_dashboard_queries(backend: BackendDriver) -> DashboardQueries:
    """Return the correct DashboardQueries for the given backend."""
    if backend.dashboard_variant == "sqlite":
        from crazyjob.dashboard.core.sqlite_queries import SQLiteDashboardQueries

        return SQLiteDashboardQueries(backend)
    return DashboardQueries(backend)


def create_dashboard_actions(backend: BackendDriver) -> DashboardActions:
    """Return the correct DashboardActions for the given backend."""
    if backend.dashboard_variant == "sqlite":
        from crazyjob.dashboard.core.sqlite_actions import SQLiteDashboardActions

        return SQLiteDashboardActions(backend)
    return DashboardActions(backend)


def create_dashboard_metrics(backend: BackendDriver) -> DashboardMetrics:
    """Return the correct DashboardMetrics for the given backend."""
    if backend.dashboard_variant == "sqlite":
        from crazyjob.dashboard.core.sqlite_metrics import SQLiteDashboardMetrics

        return SQLiteDashboardMetrics(backend)
    return DashboardMetrics(backend)
