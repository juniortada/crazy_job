"""DashboardAdapter — abstract base for framework-specific dashboard routing."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from crazyjob.dashboard.core.actions import DashboardActions
from crazyjob.dashboard.core.queries import DashboardQueries


class DashboardAdapter(ABC):
    """Wraps the pure query/action logic in HTTP routes for a specific framework."""

    def __init__(self, queries: DashboardQueries, actions: DashboardActions) -> None:
        self.q = queries
        self.a = actions

    @abstractmethod
    def get_mountable(self) -> Any:
        """Return the framework-specific router/blueprint to be registered."""
        ...
