"""FrameworkIntegration — abstract base for framework adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from crazyjob.backends.base import BackendDriver
from crazyjob.config import CrazyJobConfig


class FrameworkIntegration(ABC):
    """Every framework adapter implements these five methods.

    The core engine never calls this class directly — it is only used during
    application bootstrap.
    """

    @abstractmethod
    def get_config(self) -> CrazyJobConfig:
        """Read CrazyJob settings from the framework's native config system."""
        ...

    @abstractmethod
    def get_backend(self) -> BackendDriver:
        """Instantiate and return the configured storage driver."""
        ...

    @abstractmethod
    def setup_lifecycle_hooks(self, app: Any) -> None:
        """Register startup and shutdown handlers with the framework."""
        ...

    @abstractmethod
    def mount_dashboard(self, app: Any, url_prefix: str) -> None:
        """Register dashboard routes with the framework's router."""
        ...

    @abstractmethod
    def wrap_job_context(self, func: Callable) -> Callable:
        """Wrap job execution inside the framework's request/app context."""
        ...
