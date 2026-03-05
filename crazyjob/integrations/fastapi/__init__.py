"""FastAPI integration for CrazyJob."""
from __future__ import annotations

from typing import Any, Callable

from crazyjob.backends.base import BackendDriver
from crazyjob.config import CrazyJobConfig
from crazyjob.core.client import Client, set_client
from crazyjob.core.middleware import Middleware, MiddlewarePipeline
from crazyjob.dashboard.core.factory import create_dashboard_actions, create_dashboard_queries
from crazyjob.integrations.base import FrameworkIntegration


class FastAPICrazyJob(FrameworkIntegration):
    """FastAPI integration for CrazyJob.

    Usage::

        from fastapi import FastAPI
        from crazyjob.integrations.fastapi import FastAPICrazyJob

        app = FastAPI()
        cj = FastAPICrazyJob(app, settings={
            "database_url": "postgresql://user:pass@localhost/mydb",
        })
    """

    def __init__(self, app: Any = None, settings: dict | None = None) -> None:
        self._app = app
        self._settings = settings or {}
        self._backend: BackendDriver | None = None
        self._pipeline = MiddlewarePipeline()
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Any, settings: dict | None = None) -> None:
        """Initialize CrazyJob with a FastAPI app."""
        if settings:
            self._settings = settings
        self._app = app
        config = self.get_config()
        self._backend = self.get_backend()
        self.setup_lifecycle_hooks(app)

        client = Client(self._backend)
        set_client(client)

        app.state.crazyjob = self

        if config.dashboard_enabled:
            self.mount_dashboard(app, config.dashboard_prefix)

    def get_config(self) -> CrazyJobConfig:
        return CrazyJobConfig.from_dict(self._settings)

    def get_backend(self) -> BackendDriver:
        config = self.get_config()
        return _create_backend(config.database_url)

    def setup_lifecycle_hooks(self, app: Any) -> None:
        from fastapi import FastAPI

        if isinstance(app, FastAPI):
            original_shutdown = getattr(app, "_crazyjob_shutdown_handlers", [])

            @app.on_event("shutdown")
            def _crazyjob_shutdown() -> None:
                if self._backend:
                    self._backend.close()

    def mount_dashboard(self, app: Any, url_prefix: str) -> None:
        from crazyjob.dashboard.adapters.fastapi import FastAPIDashboardAdapter

        queries = create_dashboard_queries(self._backend)
        actions = create_dashboard_actions(self._backend)
        adapter = FastAPIDashboardAdapter(queries, actions, url_prefix=url_prefix)
        router = adapter.get_mountable()
        app.include_router(router, prefix=url_prefix)

    def wrap_job_context(self, func: Callable) -> Callable:
        # FastAPI has no app context like Flask; jobs run in worker threads
        return func

    def use(self, middleware: Middleware) -> None:
        """Register a global middleware."""
        self._pipeline.add(middleware)

    @property
    def backend(self) -> BackendDriver:
        """Access the configured backend driver."""
        if self._backend is None:
            raise RuntimeError("FastAPICrazyJob not initialized. Call init_app() first.")
        return self._backend

    @property
    def pipeline(self) -> MiddlewarePipeline:
        """Access the middleware pipeline."""
        return self._pipeline


def _create_backend(database_url: str) -> BackendDriver:
    """Create the appropriate backend driver based on URL scheme."""
    if database_url.startswith("sqlite"):
        from crazyjob.backends.sqlite.driver import SQLiteDriver

        path = database_url.replace("sqlite:///", "").replace("sqlite://", "")
        return SQLiteDriver(database_path=path or ":memory:")

    from crazyjob.backends.postgresql.driver import PostgreSQLDriver

    return PostgreSQLDriver(dsn=database_url)
