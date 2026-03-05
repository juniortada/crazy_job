"""Flask integration for CrazyJob — init_app pattern."""
from __future__ import annotations

from typing import Any, Callable

from crazyjob.backends.base import BackendDriver
from crazyjob.backends.postgresql.driver import PostgreSQLDriver
from crazyjob.config import CrazyJobConfig
from crazyjob.core.client import Client, set_client
from crazyjob.core.middleware import Middleware, MiddlewarePipeline
from crazyjob.dashboard.adapters.flask import FlaskDashboardAdapter
from crazyjob.dashboard.core.actions import DashboardActions
from crazyjob.dashboard.core.queries import DashboardQueries
from crazyjob.integrations.base import FrameworkIntegration


class FlaskCrazyJob(FrameworkIntegration):
    """Flask integration using the init_app pattern."""

    def __init__(self, app: Any = None) -> None:
        self._app = app
        self._backend: BackendDriver | None = None
        self._pipeline = MiddlewarePipeline()
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Any) -> None:
        """Initialize CrazyJob with a Flask app."""
        self._app = app
        config = self.get_config()
        self._backend = self.get_backend()
        self.setup_lifecycle_hooks(app)

        # Set global client
        client = Client(self._backend)
        set_client(client)

        if config.dashboard_enabled:
            self.mount_dashboard(app, config.dashboard_prefix)

    def get_config(self) -> CrazyJobConfig:
        return CrazyJobConfig.from_flask(self._app)

    def get_backend(self) -> BackendDriver:
        config = self.get_config()
        return PostgreSQLDriver(dsn=config.database_url)

    def setup_lifecycle_hooks(self, app: Any) -> None:
        @app.teardown_appcontext
        def close_backend(exc: Exception | None) -> None:
            # Connection pool cleanup happens at app shutdown, not per request
            pass

    def mount_dashboard(self, app: Any, url_prefix: str) -> None:
        queries = DashboardQueries(self._backend)
        actions = DashboardActions(self._backend)
        adapter = FlaskDashboardAdapter(queries, actions)
        bp = adapter.get_mountable()
        app.register_blueprint(bp, url_prefix=url_prefix)

    def wrap_job_context(self, func: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with self._app.app_context():
                return func(*args, **kwargs)

        return wrapper

    def use(self, middleware: Middleware) -> None:
        """Register a global middleware."""
        self._pipeline.add(middleware)

    @property
    def backend(self) -> BackendDriver:
        """Access the configured backend driver."""
        if self._backend is None:
            raise RuntimeError("FlaskCrazyJob not initialized. Call init_app() first.")
        return self._backend

    @property
    def pipeline(self) -> MiddlewarePipeline:
        """Access the middleware pipeline."""
        return self._pipeline
