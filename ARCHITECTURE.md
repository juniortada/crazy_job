# Conveyor — Architecture & Framework Internals

> Framework-agnostic background job processing for Python web applications, powered by PostgreSQL.

---

## Table of Contents

- [Overview](#overview)
- [Design Philosophy](#design-philosophy)
- [Layer Architecture](#layer-architecture)
  - [Layer 0 — Storage Backend](#layer-0--storage-backend)
  - [Layer 1 — Core Engine](#layer-1--core-engine)
  - [Layer 2 — Dashboard](#layer-2--dashboard)
  - [Layer 3 — Framework Integrations](#layer-3--framework-integrations)
- [Directory Structure](#directory-structure)
- [Core Abstractions](#core-abstractions)
  - [BackendDriver](#backenddriver)
  - [FrameworkIntegration](#frameworkintegration)
  - [DashboardAdapter](#dashboardadapter)
- [PostgreSQL Backend](#postgresql-backend)
  - [Database Schema](#database-schema)
  - [Concurrency Strategy](#concurrency-strategy)
  - [Job Lifecycle](#job-lifecycle)
- [Worker Engine](#worker-engine)
  - [Fetch Loop](#fetch-loop)
  - [Concurrency Model](#concurrency-model)
  - [Heartbeat & Dead Worker Detection](#heartbeat--dead-worker-detection)
  - [Graceful Shutdown](#graceful-shutdown)
- [Retry & Backoff Policies](#retry--backoff-policies)
- [Middleware Pipeline](#middleware-pipeline)
- [Scheduler (Cron Jobs)](#scheduler-cron-jobs)
- [Dashboard Internals](#dashboard-internals)
- [Adding a New Framework Integration](#adding-a-new-framework-integration)
- [Adding a New Storage Backend](#adding-a-new-storage-backend)
- [Roadmap](#roadmap)

---

## Overview

Conveyor is a background job framework inspired by Sidekiq and ActiveJob. It allows Python web applications to enqueue, process, retry, and monitor asynchronous jobs using **PostgreSQL as the only infrastructure dependency** — no Redis, no RabbitMQ, no Celery broker required.

It is designed to be **framework-agnostic**: the core engine has zero imports from Flask, Django, FastAPI, or any other web framework. Each framework is supported through a thin integration adapter that implements a well-defined contract.

```
pip install conveyor-jobs
```

---

## Design Philosophy

### 1. The core never imports from a framework
`conveyor/core/` and `conveyor/backends/` contain no references to Flask, Django, FastAPI, or Sanic. They are plain Python. This is enforced by convention and tested by import checks in CI.

### 2. Frameworks adapt to Conveyor, not the other way around
Each framework integration implements five abstract methods defined in `FrameworkIntegration`. The core doesn't know which framework is running.

### 3. The dashboard has its own logic layer
All SQL queries, metric calculations, and job actions (retry, kill, resurrect) live in `dashboard/core/` as pure Python functions that accept a database connection. The dashboard adapters (`flask.py`, `django.py`, `fastapi.py`) are thin HTTP wrappers around that logic.

### 4. One storage interface, multiple drivers
`BackendDriver` is the only interface the core uses to read and write jobs. Today it has a PostgreSQL implementation. A Redis or SQS driver can be added without changing a single line of core code.

---

## Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                            CONVEYOR                                 │
├─────────────────────────────────────────────────────────────────────┤
│  LAYER 3 — Framework Integrations                                   │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │  Flask   │  │  Django  │  │ FastAPI  │  │  Sanic   │           │
│  │ adapter  │  │ adapter  │  │ adapter  │  │ adapter  │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       └─────────────┴─────────────┴──────────────┘                 │
│                        implements ↓                                 │
│                   FrameworkIntegration (ABC)                        │
├─────────────────────────────────────────────────────────────────────┤
│  LAYER 2 — Dashboard                                                │
│                                                                     │
│  ┌──────────────────────────────────────────────┐                  │
│  │  dashboard/core/  (queries, metrics, actions) │                  │
│  │  Pure Python — no HTTP, no framework          │                  │
│  └──────────────────────┬───────────────────────┘                  │
│                         │ mounted via                               │
│  ┌──────────────────────▼───────────────────────┐                  │
│  │  dashboard/adapters/  (flask, django, fastapi) │                 │
│  └──────────────────────────────────────────────┘                  │
├─────────────────────────────────────────────────────────────────────┤
│  LAYER 1 — Core Engine                                              │
│                                                                     │
│  Job · Queue · Worker · Scheduler · Retry · Middleware              │
│  Serializer · Client · Exceptions                                   │
│                                                                     │
│  Uses only: BackendDriver (ABC)                                     │
├─────────────────────────────────────────────────────────────────────┤
│  LAYER 0 — Storage Backends                                         │
│                                                                     │
│  ┌──────────────────────┐  ┌───────────────────────────────┐       │
│  │  PostgreSQL Driver   │  │  Redis Driver  (future)        │       │
│  │  (SELECT SKIP LOCKED)│  │                                │       │
│  └──────────────────────┘  └───────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
conveyor/
│
├── core/                          # Layer 1 — zero framework imports
│   ├── __init__.py
│   ├── job.py                     # Base Job class
│   ├── queue.py                   # Queue abstraction
│   ├── worker.py                  # Worker engine (fetch loop, threads)
│   ├── scheduler.py               # Cron job runner
│   ├── client.py                  # Enqueue API (uses BackendDriver)
│   ├── serializer.py              # JSON serialization
│   ├── retry.py                   # Retry policies (linear, exponential)
│   ├── middleware.py              # Before/after job pipeline
│   └── exceptions.py             # ConveyorError, JobFailed, DeadJob
│
├── backends/                      # Layer 0 — storage drivers
│   ├── base.py                    # BackendDriver (ABC)
│   ├── postgresql/
│   │   ├── __init__.py
│   │   ├── driver.py              # SELECT SKIP LOCKED implementation
│   │   ├── schema.py              # Auto table creation
│   │   └── migrations/
│   │       └── 001_initial.sql
│   └── redis/                     # Future placeholder
│       └── __init__.py
│
├── dashboard/
│   ├── core/                      # Pure logic — no framework
│   │   ├── __init__.py
│   │   ├── queries.py             # All dashboard SQL queries
│   │   ├── metrics.py             # Throughput, latency, error rates
│   │   └── actions.py            # Resurrect, cancel, clear queue
│   └── adapters/                  # HTTP layer per framework
│       ├── base.py                # DashboardAdapter (ABC)
│       ├── flask.py               # Blueprint + Jinja2 templates
│       ├── django.py              # urls.py + class-based views (future)
│       ├── fastapi.py             # APIRouter (future)
│       └── sanic.py               # Sanic Blueprint (future)
│
├── integrations/                  # Layer 3 — framework adapters
│   ├── base.py                    # FrameworkIntegration (ABC)
│   ├── flask/
│   │   ├── __init__.py            # FlaskConveyor (init_app pattern)
│   │   └── context.py             # App context, teardown, config
│   ├── django/                    # Future
│   │   ├── __init__.py
│   │   ├── apps.py                # AppConfig
│   │   └── management/
│   │       └── commands/          # conveyor_worker management command
│   ├── fastapi/                   # Future
│   │   ├── __init__.py
│   │   └── lifespan.py
│   └── sanic/                     # Future
│       ├── __init__.py
│       └── listeners.py
│
├── cli/
│   ├── __init__.py
│   └── commands.py                # `conveyor worker`, `conveyor scheduler`
│
├── config.py                      # ConveyorConfig dataclass
└── __init__.py                    # Public API surface
```

---

## Core Abstractions

### BackendDriver

The single interface between the core engine and any storage system. Defined in `conveyor/backends/base.py`.

```python
from abc import ABC, abstractmethod
from typing import Optional
from conveyor.core.job import JobRecord


class BackendDriver(ABC):

    @abstractmethod
    def enqueue(self, job: JobRecord) -> str:
        """Insert a new job. Returns job ID."""
        ...

    @abstractmethod
    def fetch_next(self, queues: list[str]) -> Optional[JobRecord]:
        """
        Atomically fetch and lock the next available job.
        Implementation must prevent two workers from picking the same job.
        PostgreSQL: SELECT ... FOR UPDATE SKIP LOCKED
        Redis: BRPOPLPUSH or Lua script
        """
        ...

    @abstractmethod
    def mark_active(self, job_id: str, worker_id: str) -> None: ...

    @abstractmethod
    def mark_completed(self, job_id: str, result: dict) -> None: ...

    @abstractmethod
    def mark_failed(self, job_id: str, error: str, retry_at=None) -> None: ...

    @abstractmethod
    def move_to_dead(self, job_id: str, reason: str) -> None: ...

    @abstractmethod
    def register_worker(self, worker: "WorkerRecord") -> None: ...

    @abstractmethod
    def heartbeat(self, worker_id: str) -> None: ...

    @abstractmethod
    def deregister_worker(self, worker_id: str) -> None: ...
```

---

### FrameworkIntegration

Defined in `conveyor/integrations/base.py`. Every framework adapter implements these five methods. The core engine never calls this class directly — it's only used during application bootstrap.

```python
from abc import ABC, abstractmethod
from typing import Any, Callable
from conveyor.config import ConveyorConfig
from conveyor.backends.base import BackendDriver


class FrameworkIntegration(ABC):

    @abstractmethod
    def get_config(self) -> ConveyorConfig:
        """
        Read Conveyor settings from the framework's native config system.

        Flask  → app.config["CONVEYOR_DATABASE_URL"]
        Django → settings.CONVEYOR["DATABASE_URL"]
        FastAPI → Pydantic Settings instance
        """
        ...

    @abstractmethod
    def get_backend(self) -> BackendDriver:
        """
        Instantiate and return the configured storage driver.
        Should reuse the framework's existing connection pool when possible.

        Flask  → psycopg2 pool or SQLAlchemy engine
        Django → django.db.connection
        FastAPI → asyncpg pool
        """
        ...

    @abstractmethod
    def setup_lifecycle_hooks(self, app: Any) -> None:
        """
        Register startup and shutdown handlers with the framework.

        Flask  → @app.teardown_appcontext
        Django → AppConfig.ready() + post_migrate signal
        FastAPI → @asynccontextmanager lifespan
        Sanic  → @app.before_server_start / @app.after_server_stop
        """
        ...

    @abstractmethod
    def mount_dashboard(self, app: Any, url_prefix: str) -> None:
        """
        Register dashboard routes with the framework's router.

        Flask  → app.register_blueprint(blueprint, url_prefix=prefix)
        Django → path(prefix, include(dashboard_urlpatterns))
        FastAPI → app.include_router(router, prefix=prefix)
        Sanic  → app.blueprint(bp)
        """
        ...

    @abstractmethod
    def wrap_job_context(self, func: Callable) -> Callable:
        """
        Wrap job execution inside the framework's request/app context.
        This is called by the worker for every job before perform() is invoked.

        Flask  → with app.app_context(): func()
        Django → no wrapper needed (global context)
        FastAPI → asyncio.to_thread(func) or await func()
        """
        ...
```

---

### DashboardAdapter

Defined in `conveyor/dashboard/adapters/base.py`. Wraps the pure query logic in HTTP routes for a specific framework.

```python
from abc import ABC, abstractmethod
from typing import Any
from conveyor.dashboard.core.queries import DashboardQueries


class DashboardAdapter(ABC):

    def __init__(self, queries: DashboardQueries):
        self.q = queries  # Pure SQL logic, framework-agnostic

    @abstractmethod
    def get_mountable(self) -> Any:
        """
        Return the framework-specific router/blueprint to be registered.

        Flask  → flask.Blueprint
        Django → list of django.urls.path()
        FastAPI → fastapi.APIRouter
        Sanic  → sanic.Blueprint
        """
        ...
```

---

## PostgreSQL Backend

### Database Schema

Five tables power the entire system.

**`cvr_jobs`** — the primary jobs table

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `queue` | VARCHAR | Queue name (e.g. `default`, `mailers`) |
| `class_path` | VARCHAR | Dotted import path: `myapp.jobs.SendEmailJob` |
| `args` | JSONB | Positional arguments |
| `kwargs` | JSONB | Keyword arguments |
| `status` | ENUM | `enqueued`, `active`, `completed`, `failed`, `dead`, `scheduled`, `retrying` |
| `priority` | INTEGER | 0 = highest, 100 = lowest |
| `attempts` | INTEGER | Number of execution attempts |
| `max_attempts` | INTEGER | Threshold before job moves to dead letters |
| `run_at` | TIMESTAMPTZ | Earliest execution time (for scheduled/retry jobs) |
| `started_at` | TIMESTAMPTZ | When worker picked it up |
| `completed_at` | TIMESTAMPTZ | When `perform()` returned successfully |
| `failed_at` | TIMESTAMPTZ | When last exception occurred |
| `error` | TEXT | Full traceback of last failure |
| `worker_id` | VARCHAR | ID of the worker currently processing it |
| `created_at` | TIMESTAMPTZ | Enqueue time |
| `updated_at` | TIMESTAMPTZ | Last status change |

**`cvr_workers`** — active worker registry

| Column | Type | Description |
|---|---|---|
| `id` | VARCHAR | `hostname:PID` |
| `queues` | TEXT[] | Queues this worker consumes |
| `status` | ENUM | `idle`, `busy`, `stopped` |
| `current_job_id` | UUID | FK to `cvr_jobs` |
| `concurrency` | INTEGER | Thread count |
| `started_at` | TIMESTAMPTZ | Worker start time |
| `last_beat_at` | TIMESTAMPTZ | Last heartbeat (updated every 10s) |

**`cvr_dead_letters`** — exhausted jobs

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Dead letter ID |
| `original_job` | JSONB | Full snapshot of the job at time of death |
| `reason` | TEXT | Final error message |
| `killed_at` | TIMESTAMPTZ | Time of death |
| `resurrected_at` | TIMESTAMPTZ | Set if re-enqueued via dashboard |

**`cvr_schedules`** — recurring cron jobs

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Schedule ID |
| `name` | VARCHAR | Human-readable name |
| `cron` | VARCHAR | Standard cron expression: `0 9 * * 1-5` |
| `class_path` | VARCHAR | Job class to enqueue |
| `args` / `kwargs` | JSONB | Arguments to pass |
| `enabled` | BOOLEAN | Can be toggled from dashboard |
| `last_run_at` | TIMESTAMPTZ | Last trigger time |
| `next_run_at` | TIMESTAMPTZ | Precomputed next trigger time |

**`cvr_queue_pauses`** — paused queues

| Column | Type | Description |
|---|---|---|
| `queue` | VARCHAR | Queue name |
| `paused_at` | TIMESTAMPTZ | When it was paused |
| `paused_by` | VARCHAR | Actor (dashboard user, API caller) |

---

### Concurrency Strategy

Conveyor uses PostgreSQL's `SELECT ... FOR UPDATE SKIP LOCKED` to safely distribute jobs across workers without any external lock manager.

```sql
-- Worker fetch query (simplified)
BEGIN;

SELECT *
FROM cvr_jobs
WHERE status IN ('enqueued', 'retrying')
  AND (run_at IS NULL OR run_at <= NOW())
  AND queue = ANY(:queues)
ORDER BY priority ASC, created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;

-- If a row is returned, immediately mark it active
UPDATE cvr_jobs
SET status = 'active',
    started_at = NOW(),
    worker_id = :worker_id
WHERE id = :job_id;

COMMIT;
```

`SKIP LOCKED` means any row already locked by another worker is transparently skipped, not blocked. This gives true parallel job consumption with no application-level mutex needed.

---

### Job Lifecycle

```
enqueue()
    │
    ▼
┌──────────┐
│ enqueued │ ←─────────────────────────────────────────────┐
└────┬─────┘                                               │
     │  worker picks up                                    │ resurrect
     ▼                                                     │ (dashboard)
┌──────────┐     ┌───────────────┐                ┌───────┴──────┐
│  active  │────►│  completed ✓  │                │     dead     │
└────┬─────┘     └───────────────┘                └──────────────┘
     │                                                     ▲
     │  perform() raises                                   │ attempts >= max
     ▼                                                     │
┌──────────┐     attempts += 1                            │
│  failed  │────────────────────────────────────────────►─┘
└────┬─────┘                                              │
     │  attempts < max                                    │
     ▼                                                    │
┌──────────┐  run_at = now + backoff                      │
│ retrying │──────────────────────────────────────────────┘
└──────────┘  (re-enters enqueued flow when run_at passes)
```

---

## Worker Engine

### Fetch Loop

Each worker thread runs an independent fetch loop:

```
while running:
    job = backend.fetch_next(queues)

    if job is None:
        sleep(poll_interval)   # default: 1s, configurable
        continue

    try:
        with timeout(job.timeout):
            context_wrapper(job.perform)(*args, **kwargs)
        backend.mark_completed(job.id)

    except SoftTimeout:
        backend.mark_failed(job.id, "Soft timeout exceeded")
        schedule_retry_or_kill(job)

    except Exception as e:
        backend.mark_failed(job.id, traceback.format_exc())
        schedule_retry_or_kill(job)
```

### Concurrency Model

Conveyor uses a thread-pool model by default (one thread per concurrency slot). This works well for I/O-bound jobs (HTTP calls, DB writes, emails).

```
Worker Process
├── Main Thread  (fetch loop coordinator)
├── Thread 1     (fetch loop)
├── Thread 2     (fetch loop)
├── ...
├── Thread N     (fetch loop, N = --concurrency)
└── Heartbeat Thread  (writes last_beat_at every 10s)
```

For CPU-bound jobs, workers can be started as separate processes using the `--processes` flag (uses `multiprocessing` instead of `threading`).

### Heartbeat & Dead Worker Detection

Every worker writes a heartbeat to `cvr_workers.last_beat_at` every 10 seconds. A supervisor thread (running inside any active worker) periodically checks for stale entries:

```python
DEAD_THRESHOLD = timedelta(seconds=60)

stale_workers = SELECT * FROM cvr_workers
                WHERE last_beat_at < NOW() - INTERVAL '60 seconds'
                AND status != 'stopped'
```

When a stale worker is found:
1. Its `status` is set to `stopped`
2. Any jobs with `status = 'active'` and `worker_id = stale_id` are re-enqueued
3. An alert is logged

### Graceful Shutdown

On `SIGTERM` or `SIGINT`:
1. Stop accepting new jobs from the fetch loop
2. Wait for in-flight jobs to complete (up to `--shutdown-timeout`, default 30s)
3. If timeout exceeded, mark in-flight jobs as `failed` with reason `worker_shutdown`
4. Deregister worker from `cvr_workers`
5. Exit

---

## Retry & Backoff Policies

Retry behavior is configured per job class:

```python
class MyJob(Job):
    max_attempts = 5
    retry_backoff = "exponential"   # "linear" | "exponential" | custom callable
    retry_jitter = True             # adds random ±10% to avoid thundering herd
```

**Built-in strategies:**

| Strategy | Formula | Delays (attempts 1–5) |
|---|---|---|
| `linear` | `attempt * 30s` | 30s, 1m, 1.5m, 2m, 2.5m |
| `exponential` | `(2 ** attempt) * 15s` | 30s, 1m, 2m, 4m, 8m |
| `exponential_cap` | `min((2**n)*15s, 1h)` | 30s, 1m, 2m, 4m, 1h |

**Custom policy:**

```python
def my_backoff(attempt: int) -> timedelta:
    return timedelta(seconds=attempt * 45)

class MyJob(Job):
    retry_backoff = my_backoff
```

---

## Middleware Pipeline

Middleware wraps every job execution. Built-in middleware includes logging, error tracking, and APM spans. Custom middleware can be added globally or per job class.

```python
# Global middleware registration
conveyor.use(LoggingMiddleware())
conveyor.use(SentryMiddleware(dsn="..."))

# Custom middleware
from conveyor.core.middleware import Middleware

class MyMiddleware(Middleware):
    def before_perform(self, job: JobRecord) -> None:
        print(f"Starting {job.class_path}")

    def after_perform(self, job: JobRecord, result: Any) -> None:
        print(f"Finished {job.class_path}")

    def on_failure(self, job: JobRecord, error: Exception) -> None:
        notify_team(error)
```

---

## Scheduler (Cron Jobs)

The scheduler is a separate process (`conveyor scheduler`) that:

1. Reads all enabled entries from `cvr_schedules`
2. Finds entries where `next_run_at <= NOW()`
3. Enqueues the corresponding job class
4. Updates `last_run_at` and recomputes `next_run_at` using `croniter`

Uses `SELECT ... FOR UPDATE SKIP LOCKED` on `cvr_schedules` so multiple scheduler processes don't double-fire the same schedule.

---

## Dashboard Internals

The dashboard is structured so that every action is a pure Python function that takes a database connection and returns data:

```python
# conveyor/dashboard/core/queries.py

class DashboardQueries:
    def __init__(self, backend: BackendDriver):
        self.backend = backend

    def overview_stats(self) -> dict:
        """Returns counts per status, throughput (jobs/min), error rate."""
        ...

    def list_jobs(self, status, queue=None, page=1, per_page=25) -> list[JobRecord]:
        ...

    def list_workers(self) -> list[WorkerRecord]:
        ...

    def list_dead_letters(self, page=1) -> list[DeadLetterRecord]:
        ...
```

```python
# conveyor/dashboard/core/actions.py

class DashboardActions:
    def resurrect(self, dead_letter_id: str) -> str:
        """Re-enqueue a dead job. Returns new job ID."""
        ...

    def cancel(self, job_id: str) -> None:
        """Remove an enqueued job before it's picked up."""
        ...

    def pause_queue(self, queue: str) -> None: ...
    def resume_queue(self, queue: str) -> None: ...
    def clear_queue(self, queue: str) -> None: ...
    def bulk_resurrect(self) -> int:
        """Resurrect all dead letters. Returns count."""
        ...
```

The Flask adapter then calls these functions from its route handlers:

```python
# conveyor/dashboard/adapters/flask.py

@bp.route("/")
def overview():
    stats = queries.overview_stats()
    return render_template("overview.html", stats=stats)

@bp.post("/dead/<dead_id>/resurrect")
def resurrect(dead_id):
    new_id = actions.resurrect(dead_id)
    flash(f"Job re-enqueued as {new_id}", "success")
    return redirect(url_for(".dead_letters"))
```

When Django support is added, `DashboardQueries` and `DashboardActions` are reused as-is. Only the route handler file changes.

---

## Adding a New Framework Integration

To add support for a new framework, create a new directory under `conveyor/integrations/` and implement `FrameworkIntegration`:

```python
# conveyor/integrations/myframework/__init__.py

from conveyor.integrations.base import FrameworkIntegration
from conveyor.backends.postgresql import PostgreSQLDriver
from conveyor.config import ConveyorConfig
from conveyor.dashboard.adapters.myframework import MyFrameworkDashboardAdapter


class MyFrameworkConveyor(FrameworkIntegration):

    def get_config(self) -> ConveyorConfig:
        # Read from your framework's config system
        ...

    def get_backend(self) -> PostgreSQLDriver:
        # Return a configured driver instance
        ...

    def setup_lifecycle_hooks(self, app) -> None:
        # Register startup/shutdown with your framework
        ...

    def mount_dashboard(self, app, url_prefix: str) -> None:
        adapter = MyFrameworkDashboardAdapter(self.queries)
        mountable = adapter.get_mountable()
        # Register mountable with your framework's router
        ...

    def wrap_job_context(self, func):
        # Wrap in your framework's app context, if needed
        ...
```

Then create `conveyor/dashboard/adapters/myframework.py` implementing `DashboardAdapter.get_mountable()`.

**That's all.** No changes to core, worker, retry, serializer, or scheduler.

---

## Adding a New Storage Backend

Create a new directory under `conveyor/backends/` and implement `BackendDriver`:

```python
# conveyor/backends/redis/driver.py

from conveyor.backends.base import BackendDriver

class RedisDriver(BackendDriver):

    def __init__(self, redis_url: str):
        self.client = Redis.from_url(redis_url)

    def enqueue(self, job: JobRecord) -> str:
        # Serialize and LPUSH to the queue list
        ...

    def fetch_next(self, queues: list[str]) -> Optional[JobRecord]:
        # BRPOPLPUSH for atomic pop-and-backup
        ...

    # Implement remaining abstract methods...
```

Pass it to the worker:

```python
from conveyor.backends.redis import RedisDriver
from conveyor.core.worker import Worker

worker = Worker(
    backend=RedisDriver("redis://localhost:6379"),
    queues=["default"],
    concurrency=10
)
```

---

## Roadmap

| Phase | Milestone | Status |
|---|---|---|
| 1 | PostgreSQL schema + migrations | 🔲 Planned |
| 2 | `BackendDriver` + PostgreSQL driver | 🔲 Planned |
| 3 | Core engine (Job, Queue, Client, Serializer, Retry) | 🔲 Planned |
| 4 | Worker engine (fetch loop, heartbeat, shutdown) | 🔲 Planned |
| 5 | `FrameworkIntegration` ABC + Flask adapter | 🔲 Planned |
| 6 | `DashboardAdapter` ABC + dashboard core queries | 🔲 Planned |
| 7 | Flask dashboard adapter (Blueprint + HTMX templates) | 🔲 Planned |
| 8 | CLI (`conveyor worker`, `conveyor scheduler`) | 🔲 Planned |
| 9 | Middleware pipeline + built-in middleware | 🔲 Planned |
| 10 | Test suite + CI | 🔲 Planned |
| 11 | PyPI release + documentation | 🔲 Planned |
| — | Django integration | 🔵 Future |
| — | FastAPI integration | 🔵 Future |
| — | Sanic integration | 🔵 Future |
| — | Redis backend driver | 🔵 Future |

---

*Conveyor is under active development. APIs marked as stable will follow semantic versioning. Contributions welcome — please read `CONTRIBUTING.md` before opening a PR.*
