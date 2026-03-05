# CONVENTIONS.md — CrazyJob Code Patterns & Examples

Reference for consistent implementation patterns across the codebase.
Claude should follow these patterns exactly when generating code.

---

## JobRecord Dataclass

The canonical in-memory representation of a job. Used everywhere between layers.

```python
# crazyjob/core/job.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass
class JobRecord:
    class_path: str
    args: list
    kwargs: dict
    queue: str = "default"
    priority: int = 50
    max_attempts: int = 3
    id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "enqueued"
    attempts: int = 0
    run_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    error: str | None = None
    worker_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    meta: dict = field(default_factory=dict)


@dataclass
class WorkerRecord:
    id: str                          # hostname:PID
    queues: list[str]
    concurrency: int
    status: str = "idle"             # idle | busy | stopped
    current_job_id: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    last_beat_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DeadLetterRecord:
    id: str
    original_job: dict               # full JobRecord snapshot as dict
    reason: str
    killed_at: datetime
    resurrected_at: datetime | None = None
```

---

## Base Job Class

```python
# crazyjob/core/job.py (continued)
from __future__ import annotations
from datetime import timedelta
from typing import Any, ClassVar
from crazyjob.core.client import get_client


class Job:
    # Class-level configuration — override in subclasses
    queue: ClassVar[str] = "default"
    max_attempts: ClassVar[int] = 3
    retry_backoff: ClassVar[str | callable] = "exponential"
    retry_jitter: ClassVar[bool] = True
    timeout: ClassVar[timedelta | None] = None
    priority: ClassVar[int] = 50

    def perform(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    @classmethod
    def enqueue(cls, *args: Any, **kwargs: Any) -> str:
        return get_client().enqueue(cls, args=list(args), kwargs=kwargs)

    @classmethod
    def enqueue_in(cls, delay: timedelta, *args: Any, **kwargs: Any) -> str:
        return get_client().enqueue(cls, args=list(args), kwargs=kwargs, delay=delay)

    @classmethod
    def enqueue_at(cls, run_at: datetime, *args: Any, **kwargs: Any) -> str:
        return get_client().enqueue(cls, args=list(args), kwargs=kwargs, run_at=run_at)

    @classmethod
    def _class_path(cls) -> str:
        return f"{cls.__module__}.{cls.__qualname__}"
```

---

## PostgreSQL Driver Patterns

### Connection management

```python
# crazyjob/backends/postgresql/driver.py
import psycopg2
import psycopg2.pool
from contextlib import contextmanager
from crazyjob.backends.base import BackendDriver


class PostgreSQLDriver(BackendDriver):

    def __init__(self, dsn: str, min_conn: int = 1, max_conn: int = 10) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(min_conn, max_conn, dsn)

    @contextmanager
    def _conn(self):
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    @contextmanager
    def _cursor(self):
        with self._conn() as conn:
            with conn.cursor() as cur:
                yield cur

    def close(self) -> None:
        self._pool.closeall()
```

### Fetch with SKIP LOCKED

```python
    def fetch_next(self, queues: list[str]) -> JobRecord | None:
        sql = """
            WITH next_job AS (
                SELECT id FROM cj_jobs
                WHERE status IN ('enqueued', 'retrying')
                  AND (run_at IS NULL OR run_at <= NOW())
                  AND queue = ANY(%s)
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE cj_jobs
            SET status = 'active', updated_at = NOW()
            FROM next_job
            WHERE cj_jobs.id = next_job.id
            RETURNING cj_jobs.*;
        """
        with self._cursor() as cur:
            cur.execute(sql, (queues,))
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_job_record(cur, row)
```

---

## Retry Policy Pattern

```python
# crazyjob/core/retry.py
from __future__ import annotations
import random
from abc import ABC, abstractmethod
from datetime import timedelta


class BackoffPolicy(ABC):
    @abstractmethod
    def delay_for(self, attempt: int) -> timedelta: ...


class ExponentialBackoff(BackoffPolicy):
    def __init__(self, base_seconds: int = 15, jitter: bool = True) -> None:
        self.base_seconds = base_seconds
        self.jitter = jitter

    def delay_for(self, attempt: int) -> timedelta:
        seconds = (2 ** attempt) * self.base_seconds
        if self.jitter:
            seconds *= random.uniform(0.9, 1.1)
        return timedelta(seconds=seconds)


class LinearBackoff(BackoffPolicy):
    def __init__(self, base_seconds: int = 30, jitter: bool = True) -> None:
        self.base_seconds = base_seconds
        self.jitter = jitter

    def delay_for(self, attempt: int) -> timedelta:
        seconds = attempt * self.base_seconds
        if self.jitter:
            seconds *= random.uniform(0.9, 1.1)
        return timedelta(seconds=seconds)


class ExponentialCapBackoff(BackoffPolicy):
    def __init__(self, base_seconds: int = 15, cap_seconds: int = 3600, jitter: bool = True) -> None:
        self.base_seconds = base_seconds
        self.cap_seconds = cap_seconds
        self.jitter = jitter

    def delay_for(self, attempt: int) -> timedelta:
        seconds = min((2 ** attempt) * self.base_seconds, self.cap_seconds)
        if self.jitter:
            seconds *= random.uniform(0.9, 1.1)
        return timedelta(seconds=seconds)


def get_backoff_policy(name: str | BackoffPolicy | callable) -> BackoffPolicy:
    if isinstance(name, BackoffPolicy):
        return name
    if callable(name):
        # Wrap raw callable in a BackoffPolicy
        return _CallablePolicy(name)
    policies = {
        "linear": LinearBackoff,
        "exponential": ExponentialBackoff,
        "exponential_cap": ExponentialCapBackoff,
    }
    if name not in policies:
        raise ValueError(f"Unknown backoff policy: {name!r}. Choose from {list(policies)}")
    return policies[name]()


class _CallablePolicy(BackoffPolicy):
    def __init__(self, fn: callable) -> None:
        self._fn = fn

    def delay_for(self, attempt: int) -> timedelta:
        return self._fn(attempt)
```

---

## Middleware Pattern

```python
# crazyjob/core/middleware.py
from __future__ import annotations
from abc import ABC
from typing import Any, Callable
from crazyjob.core.job import JobRecord


class Middleware(ABC):
    def before_perform(self, job: JobRecord) -> None:
        pass

    def after_perform(self, job: JobRecord, result: Any) -> None:
        pass

    def on_failure(self, job: JobRecord, error: Exception) -> None:
        pass


class MiddlewarePipeline:
    def __init__(self, middlewares: list[Middleware]) -> None:
        self._middlewares = middlewares

    def run(self, job: JobRecord, perform_fn: Callable) -> Any:
        for mw in self._middlewares:
            mw.before_perform(job)
        try:
            result = perform_fn()
            for mw in self._middlewares:
                mw.after_perform(job, result)
            return result
        except Exception as e:
            for mw in self._middlewares:
                mw.on_failure(job, e)
            raise
```

---

## Flask Integration Pattern

```python
# crazyjob/integrations/flask/__init__.py
from __future__ import annotations
from typing import Any, Callable
from crazyjob.integrations.base import FrameworkIntegration
from crazyjob.config import CrazyJobConfig
from crazyjob.backends.base import BackendDriver
from crazyjob.backends.postgresql.driver import PostgreSQLDriver
from crazyjob.dashboard.core.queries import DashboardQueries
from crazyjob.dashboard.core.actions import DashboardActions
from crazyjob.dashboard.adapters.flask import FlaskDashboardAdapter


class FlaskCrazyJob(FrameworkIntegration):

    def __init__(self, app: Any = None) -> None:
        self._app = app
        self._backend: BackendDriver | None = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Any) -> None:
        self._app = app
        config = self.get_config()
        self._backend = self.get_backend()
        self.setup_lifecycle_hooks(app)
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

    def use(self, middleware: Any) -> None:
        # Register global middleware
        ...
```

---

## Config Dataclass

```python
# crazyjob/config.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CrazyJobConfig:
    database_url: str
    queues: list[str] = field(default_factory=lambda: ["default"])
    default_max_attempts: int = 3
    default_backoff: str = "exponential"
    poll_interval: float = 1.0
    job_timeout: int | None = None
    dead_letter_ttl_days: int = 30
    dashboard_enabled: bool = True
    dashboard_prefix: str = "/crazyjob"
    dashboard_auth: tuple[str, str] | callable | None = None
    use_sqlalchemy: bool = False
    heartbeat_interval: int = 10
    dead_worker_threshold: int = 60

    @classmethod
    def from_flask(cls, app: Any) -> CrazyJobConfig:
        c = app.config
        return cls(
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

    @classmethod
    def from_dict(cls, d: dict) -> CrazyJobConfig:
        return cls(**{k.lower(): v for k, v in d.items()})
```

---

## Database Migration SQL

```sql
-- crazyjob/backends/postgresql/migrations/001_initial.sql

-- Job status enum
CREATE TYPE cj_job_status AS ENUM (
    'enqueued', 'active', 'completed', 'failed', 'dead', 'scheduled', 'retrying'
);

-- Worker status enum
CREATE TYPE cj_worker_status AS ENUM ('idle', 'busy', 'stopped');

-- Primary jobs table
CREATE TABLE IF NOT EXISTS cj_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    queue           VARCHAR(255) NOT NULL DEFAULT 'default',
    class_path      VARCHAR(500) NOT NULL,
    args            JSONB NOT NULL DEFAULT '[]',
    kwargs          JSONB NOT NULL DEFAULT '{}',
    status          cj_job_status NOT NULL DEFAULT 'enqueued',
    priority        INTEGER NOT NULL DEFAULT 50,
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    run_at          TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    failed_at       TIMESTAMPTZ,
    error           TEXT,
    worker_id       VARCHAR(500),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for worker fetch query performance
CREATE INDEX IF NOT EXISTS idx_cj_jobs_fetch
    ON cj_jobs (priority ASC, created_at ASC)
    WHERE status IN ('enqueued', 'retrying');

CREATE INDEX IF NOT EXISTS idx_cj_jobs_queue_status
    ON cj_jobs (queue, status);

CREATE INDEX IF NOT EXISTS idx_cj_jobs_run_at
    ON cj_jobs (run_at)
    WHERE run_at IS NOT NULL AND status IN ('enqueued', 'retrying', 'scheduled');

-- Worker registry
CREATE TABLE IF NOT EXISTS cj_workers (
    id              VARCHAR(500) PRIMARY KEY,
    queues          TEXT[] NOT NULL,
    concurrency     INTEGER NOT NULL DEFAULT 1,
    status          cj_worker_status NOT NULL DEFAULT 'idle',
    current_job_id  UUID REFERENCES cj_jobs(id) ON DELETE SET NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_beat_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Dead letters
CREATE TABLE IF NOT EXISTS cj_dead_letters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_job    JSONB NOT NULL,
    reason          TEXT NOT NULL,
    killed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resurrected_at  TIMESTAMPTZ
);

-- Recurring cron schedules
CREATE TABLE IF NOT EXISTS cj_schedules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL UNIQUE,
    cron            VARCHAR(100) NOT NULL,
    class_path      VARCHAR(500) NOT NULL,
    args            JSONB NOT NULL DEFAULT '[]',
    kwargs          JSONB NOT NULL DEFAULT '{}',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at     TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Queue pauses
CREATE TABLE IF NOT EXISTS cj_queue_pauses (
    queue           VARCHAR(255) PRIMARY KEY,
    paused_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paused_by       VARCHAR(255)
);
```

---

## Test conftest.py Pattern

```python
# tests/conftest.py
from __future__ import annotations
import pytest
from pytest_postgresql import factories
from crazyjob.backends.postgresql.driver import PostgreSQLDriver
from crazyjob.backends.postgresql.schema import apply_schema
from crazyjob.core.job import JobRecord


postgresql_proc = factories.postgresql_proc(port=None)
postgresql = factories.postgresql("postgresql_proc")


@pytest.fixture()
def backend(postgresql):
    dsn = (
        f"host={postgresql.info.host} "
        f"port={postgresql.info.port} "
        f"dbname={postgresql.info.dbname} "
        f"user={postgresql.info.user}"
    )
    driver = PostgreSQLDriver(dsn=dsn)
    apply_schema(driver)
    yield driver
    driver.close()


@pytest.fixture()
def job_factory(backend):
    class _Factory:
        def enqueue(
            self,
            backend=backend,
            queue: str = "default",
            class_path: str = "tests.helpers.jobs.NoOpJob",
            kwargs: dict | None = None,
            max_attempts: int = 3,
            priority: int = 50,
        ) -> JobRecord:
            record = JobRecord(
                class_path=class_path,
                args=[],
                kwargs=kwargs or {},
                queue=queue,
                max_attempts=max_attempts,
                priority=priority,
            )
            job_id = backend.enqueue(record)
            record.id = job_id
            return record
    return _Factory()
```

---

## pyproject.toml Template

```toml
[project]
name = "crazyjob"
version = "0.1.0"
description = "Framework-agnostic background job processing for Python, powered by PostgreSQL"
requires-python = ">=3.10"
license = {text = "MIT"}
dependencies = [
    "psycopg2-binary>=2.9",
    "click>=8.1",
    "croniter>=2.0",
]

[project.optional-dependencies]
flask = ["flask>=3.0"]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-mock>=3.12",
    "pytest-postgresql>=5.0",
    "factory-boy>=3.3",
    "ruff>=0.4",
    "black>=24.0",
    "mypy>=1.9",
    "bandit>=1.7",
    "pre-commit>=3.7",
    "types-psycopg2",
    "types-croniter",
]

[project.scripts]
crazyjob = "crazyjob.cli.commands:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
target-version = "py310"
line-length = 100

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B", "C4", "SIM", "TCH", "RUF"]
ignore = ["E501"]

[tool.ruff.lint.isort]
known-first-party = ["crazyjob"]

[tool.black]
line-length = 100
target-version = ["py310", "py311", "py312"]

[tool.mypy]
python_version = "3.10"
strict = true
ignore_missing_imports = true
disallow_untyped_defs = true
warn_return_any = true
warn_unused_ignores = true

[[tool.mypy.overrides]]
module = ["crazyjob.core.*", "crazyjob.backends.*"]
disallow_any_explicit = true

[tool.bandit]
exclude_dirs = ["tests"]
skips = ["B101"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=crazyjob --cov-report=term-missing --cov-fail-under=85"
markers = [
    "unit: pure unit tests, no I/O",
    "integration: tests that require a real PostgreSQL instance",
    "e2e: full worker lifecycle tests with real threads",
]

[tool.coverage.run]
source = ["crazyjob"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "@abstractmethod",
]
fail_under = 85
```
