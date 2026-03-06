"""Flask integration for CrazyJob — init_app pattern.

Also exposes config_from_flask() as the framework-specific config factory.
SRP: framework-specific factories live here, not in core CrazyJobConfig.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from crazyjob.config import CrazyJobConfig
from crazyjob.core.client import Client, set_client
from crazyjob.core.middleware import Middleware, MiddlewarePipeline
from crazyjob.dashboard.adapters.flask import FlaskDashboardAdapter
from crazyjob.dashboard.core.factory import create_dashboard_actions, create_dashboard_queries
from crazyjob.integrations.base import FrameworkIntegration

if TYPE_CHECKING:
    from collections.abc import Callable

    from crazyjob.backends.base import BackendDriver


def config_from_flask(app: Any) -> CrazyJobConfig:
    """Build CrazyJobConfig from a Flask app's config dict.

    Usage::

        from crazyjob.integrations.flask import config_from_flask

        cfg = config_from_flask(app)
    """
    c = app.config
    return CrazyJobConfig(
        database_url=c["CRAZYJOB_DATABASE_URL"],
        queues=c.get("CRAZYJOB_QUEUES", ["default"]),
        default_max_attempts=c.get("CRAZYJOB_DEFAULT_MAX_ATTEMPTS", 3),
        default_backoff=c.get("CRAZYJOB_DEFAULT_BACKOFF", "exponential"),
        poll_interval=c.get("CRAZYJOB_POLL_INTERVAL", 1.0),
        job_timeout=c.get("CRAZYJOB_JOB_TIMEOUT"),
        dead_letter_ttl_days=c.get("CRAZYJOB_DEAD_LETTER_TTL_DAYS", 30),
        dashboard_enabled=c.get("CRAZYJOB_DASHBOARD_ENABLED", True),
        dashboard_prefix=c.get("CRAZYJOB_DASHBOARD_PREFIX", "/crazyjob"),
        dashboard_auth=c.get("CRAZYJOB_DASHBOARD_AUTH"),
        use_sqlalchemy=c.get("CRAZYJOB_USE_SQLALCHEMY", False),
        heartbeat_interval=c.get("CRAZYJOB_HEARTBEAT_INTERVAL", 10),
        dead_worker_threshold=c.get("CRAZYJOB_DEAD_WORKER_THRESHOLD", 60),
    )


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
        return config_from_flask(self._app)

    def get_backend(self) -> BackendDriver:
        config = self.get_config()
        return _create_backend(config.database_url)

    def setup_lifecycle_hooks(self, app: Any) -> None:
        @app.teardown_appcontext  # type: ignore[untyped-decorator]
        def close_backend(exc: Exception | None) -> None:
            # Connection pool cleanup happens at app shutdown, not per request
            pass

    def mount_dashboard(self, app: Any, url_prefix: str) -> None:
        queries = create_dashboard_queries(self.backend)
        actions = create_dashboard_actions(self.backend)
        adapter = FlaskDashboardAdapter(queries, actions)
        bp = adapter.get_mountable()
        app.register_blueprint(bp, url_prefix=url_prefix)

    def wrap_job_context(self, func: Callable[..., object]) -> Callable[..., object]:
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


def _create_backend(database_url: str) -> BackendDriver:
    """Create the appropriate backend driver based on URL scheme."""
    if database_url.startswith("sqlite"):
        from crazyjob.backends.sqlite.driver import SQLiteDriver

        path = database_url.replace("sqlite:///", "").replace("sqlite://", "")
        return SQLiteDriver(database_path=path or ":memory:")

    from crazyjob.backends.postgresql.driver import PostgreSQLDriver

    return PostgreSQLDriver(dsn=database_url)
