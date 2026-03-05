# CrazyJob — Architecture & Framework Internals

> Framework-agnostic background job processing for Python web applications, powered by PostgreSQL or SQLite.

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
- [Storage Backends](#storage-backends)
  - [PostgreSQL Backend](#postgresql-backend)
    - [Database Schema](#database-schema)
    - [Concurrency Strategy](#concurrency-strategy)
  - [SQLite Backend](#sqlite-backend)
    - [Type Mapping](#type-mapping)
    - [Concurrency Strategy (SQLite)](#concurrency-strategy-sqlite)
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
  - [Dashboard SQL Compatibility](#dashboard-sql-compatibility)
- [Flask Integration](#flask-integration)
- [FastAPI Integration](#fastapi-integration)
- [Adding a New Framework Integration](#adding-a-new-framework-integration)
- [Adding a New Storage Backend](#adding-a-new-storage-backend)
- [Code Quality & Linting](#code-quality--linting)
  - [Tools](#tools)
  - [Configuration Files](#configuration-files)
  - [Pre-commit Hooks](#pre-commit-hooks)
  - [CI Lint Pipeline](#ci-lint-pipeline)
- [Testing Strategy](#testing-strategy)
  - [Test Layout](#test-layout)
  - [Test Layers](#test-layers)
  - [Unit Tests](#unit-tests)
  - [Integration Tests](#integration-tests)
  - [End-to-End Tests](#end-to-end-tests)
  - [Running Tests](#running-tests)
  - [Coverage](#coverage)
- [Docker & Docker Compose](#docker--docker-compose)
  - [Dockerfile](#dockerfile)
  - [Docker Compose — Development](#docker-compose--development)
  - [Docker Compose — CI](#docker-compose--ci)
  - [Docker Compose — Production Reference](#docker-compose--production-reference)
- [CI/CD Pipeline](#cicd-pipeline)
- [Roadmap](#roadmap)

---

## Overview

CrazyJob is a background job framework inspired by Sidekiq and ActiveJob. It allows Python web applications to enqueue, process, retry, and monitor asynchronous jobs using **PostgreSQL or SQLite** — no Redis, no RabbitMQ, no Celery broker required.

It is designed to be **framework-agnostic**: the core engine has zero imports from Flask, Django, FastAPI, or any other web framework. Each framework is supported through a thin integration adapter that implements a well-defined contract.

```bash
pip install crazyjob                     # core only (SQLite built-in)
pip install "crazyjob[postgresql]"       # + PostgreSQL driver
pip install "crazyjob[flask]"            # + Flask integration
pip install "crazyjob[fastapi]"          # + FastAPI integration
```

---

## Design Philosophy

### 1. The core never imports from a framework
`crazyjob/core/` and `crazyjob/backends/` contain no references to Flask, Django, FastAPI, or Sanic. They are plain Python. This is enforced by convention and verified by an automated import boundary check that runs in CI on every push.

### 2. Frameworks adapt to CrazyJob, not the other way around
Each framework integration implements five abstract methods defined in `FrameworkIntegration`. The core doesn't know which framework is running.

### 3. The dashboard has its own logic layer
All SQL queries, metric calculations, and job actions (retry, kill, resurrect) live in `dashboard/core/` as pure Python functions that accept a database connection. The dashboard adapters (`flask.py`, `django.py`, `fastapi.py`) are thin HTTP wrappers around that logic.

### 4. One storage interface, multiple drivers
`BackendDriver` is the only interface the core uses to read and write jobs. The PostgreSQL driver is the reference implementation. Any future driver must satisfy the same interface without touching core code.

---

## Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                            CRAZYJOB                                 │
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
│  LAYER 0 — Storage Backend                                          │
│                                                                     │
│  ┌──────────────────────────────────────────────┐                  │
│  │  PostgreSQL Driver  (SELECT ... SKIP LOCKED)  │                  │
│  └──────────────────────────────────────────────┘                  │
│  ┌──────────────────────────────────────────────┐                  │
│  │  SQLite Driver  (BEGIN IMMEDIATE + Lock)      │                  │
│  └──────────────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
crazyjob/
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
│   └── exceptions.py             # CrazyJobError, JobFailed, DeadJob
│
├── backends/                      # Layer 0 — storage drivers
│   ├── base.py                    # BackendDriver (ABC)
│   ├── postgresql/
│   │   ├── __init__.py
│   │   ├── driver.py              # SELECT SKIP LOCKED implementation
│   │   ├── schema.py              # Auto table creation
│   │   └── migrations/
│   │       └── 001_initial.sql
│   └── sqlite/
│       ├── __init__.py
│       ├── driver.py              # BEGIN IMMEDIATE + threading.Lock
│       ├── schema.py              # apply_schema()
│       └── migrations/
│           └── 001_initial.sql
│
├── dashboard/
│   ├── core/                      # Pure logic — no framework
│   │   ├── __init__.py
│   │   ├── queries.py             # PostgreSQL dashboard queries
│   │   ├── metrics.py             # PostgreSQL dashboard metrics
│   │   ├── actions.py             # PostgreSQL dashboard actions
│   │   ├── sqlite_queries.py      # SQLite-specific query overrides
│   │   ├── sqlite_metrics.py      # SQLite-specific metric overrides
│   │   ├── sqlite_actions.py      # SQLite-specific action overrides
│   │   └── factory.py             # Auto-detect backend → correct classes
│   └── adapters/                  # HTTP layer per framework
│       ├── base.py                # DashboardAdapter (ABC)
│       ├── flask.py               # Blueprint + Jinja2
│       ├── fastapi.py             # APIRouter + Jinja2Templates
│       ├── django.py              # urls.py + class-based views (future)
│       └── sanic.py               # Sanic Blueprint (future)
│
├── integrations/                  # Layer 3 — framework adapters
│   ├── base.py                    # FrameworkIntegration (ABC)
│   ├── flask/
│   │   └── __init__.py            # FlaskCrazyJob (init_app pattern)
│   ├── fastapi/
│   │   └── __init__.py            # FastAPICrazyJob (settings dict)
│   ├── django/                    # Future
│   │   ├── __init__.py
│   │   ├── apps.py                # AppConfig
│   │   └── management/
│   │       └── commands/          # crazyjob_worker management command
│   └── sanic/                     # Future
│       ├── __init__.py
│       └── listeners.py
│
├── cli/
│   ├── __init__.py
│   └── commands.py                # `crazyjob worker`, `crazyjob scheduler`
│
├── config.py                      # CrazyJobConfig dataclass
└── __init__.py                    # Public API surface
```

---

## Core Abstractions

### BackendDriver

The single interface between the core engine and any storage system. Defined in `crazyjob/backends/base.py`.

```python
from abc import ABC, abstractmethod
from datetime import datetime
from crazyjob.core.job import JobRecord, WorkerRecord, DeadLetterRecord


class BackendDriver(ABC):

    @abstractmethod
    def enqueue(self, job: JobRecord) -> str:
        """Insert a new job. Returns job ID."""
        ...

    @abstractmethod
    def fetch_next(self, queues: list[str]) -> JobRecord | None:
        """
        Atomically fetch, lock, and claim the next job.
        Must increment attempts and set started_at in the SAME transaction.
        Never split this into two queries. See Queue Poisoning rules in CLAUDE.md.
        PostgreSQL: WITH ... SELECT FOR UPDATE SKIP LOCKED ... UPDATE ... RETURNING
        """
        ...

    @abstractmethod
    def mark_completed(self, job_id: str, result: dict) -> None: ...

    @abstractmethod
    def mark_failed(self, job_id: str, error: str, retry_at: datetime | None = None) -> None: ...

    @abstractmethod
    def move_to_dead(self, job_id: str, reason: str) -> None: ...

    @abstractmethod
    def register_worker(self, worker: WorkerRecord) -> None: ...

    @abstractmethod
    def heartbeat(self, worker_id: str) -> None: ...

    @abstractmethod
    def deregister_worker(self, worker_id: str) -> None: ...

    @abstractmethod
    def get_job(self, job_id: str) -> JobRecord | None: ...

    @abstractmethod
    def get_dead_letter(self, job_id: str) -> DeadLetterRecord | None: ...
```

Note: `mark_active` is **not** a separate method. Claiming a job (setting it active, recording `worker_id`, `started_at`, incrementing `attempts`) happens inside `fetch_next` atomically. There is no separate "mark active" step.

---

### FrameworkIntegration

Defined in `crazyjob/integrations/base.py`. Every framework adapter implements these five methods. The core engine never calls this class directly — it is only used during application bootstrap.

```python
from abc import ABC, abstractmethod
from typing import Any, Callable
from crazyjob.config import CrazyJobConfig
from crazyjob.backends.base import BackendDriver


class FrameworkIntegration(ABC):

    @abstractmethod
    def get_config(self) -> CrazyJobConfig:
        """
        Read CrazyJob settings from the framework's native config system.

        Flask  → app.config["CRAZYJOB_DATABASE_URL"]
        Django → settings.CRAZYJOB["DATABASE_URL"]
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
        Called by the worker for every job before perform() is invoked.

        Flask  → with app.app_context(): func()
        Django → no wrapper needed (global context)
        FastAPI → asyncio.to_thread(func) or await func()
        """
        ...
```

---

### DashboardAdapter

Defined in `crazyjob/dashboard/adapters/base.py`. Wraps the pure query logic in HTTP routes for a specific framework.

```python
from abc import ABC, abstractmethod
from typing import Any
from crazyjob.dashboard.core.queries import DashboardQueries
from crazyjob.dashboard.core.actions import DashboardActions


class DashboardAdapter(ABC):

    def __init__(self, queries: DashboardQueries, actions: DashboardActions) -> None:
        self.q = queries    # Pure SQL logic, framework-agnostic
        self.a = actions    # Job actions (resurrect, cancel, pause, etc.)

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

## Storage Backends

### PostgreSQL Backend

#### Database Schema

Five tables power the entire system. All table names are prefixed with `cj_` to avoid conflicts with application tables.

**`cj_jobs`** — the primary jobs table

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `queue` | VARCHAR | Queue name (e.g. `default`, `mailers`) |
| `class_path` | VARCHAR | Dotted import path: `myapp.jobs.SendEmailJob` |
| `args` | JSONB | Positional arguments |
| `kwargs` | JSONB | Keyword arguments |
| `status` | ENUM | `enqueued`, `active`, `completed`, `failed`, `dead`, `scheduled`, `retrying` |
| `priority` | INTEGER | 0 = highest, 100 = lowest |
| `attempts` | INTEGER | Number of execution attempts so far |
| `max_attempts` | INTEGER | Threshold before job moves to dead letters |
| `run_at` | TIMESTAMPTZ | Earliest execution time (scheduled/retry jobs) |
| `started_at` | TIMESTAMPTZ | When worker picked it up |
| `completed_at` | TIMESTAMPTZ | When `perform()` returned successfully |
| `failed_at` | TIMESTAMPTZ | When last exception occurred |
| `error` | TEXT | Full traceback of last failure |
| `worker_id` | VARCHAR | ID of the worker currently processing it |
| `created_at` | TIMESTAMPTZ | Enqueue time |
| `updated_at` | TIMESTAMPTZ | Last status change |

**`cj_workers`** — active worker registry

| Column | Type | Description |
|---|---|---|
| `id` | VARCHAR | `hostname:PID` |
| `queues` | TEXT[] | Queues this worker consumes |
| `status` | ENUM | `idle`, `busy`, `stopped` |
| `current_job_id` | UUID | FK to `cj_jobs` |
| `concurrency` | INTEGER | Thread count |
| `started_at` | TIMESTAMPTZ | Worker start time |
| `last_beat_at` | TIMESTAMPTZ | Last heartbeat (updated every 10s) |

**`cj_dead_letters`** — exhausted jobs

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Dead letter ID |
| `original_job` | JSONB | Full snapshot of the job at time of death |
| `reason` | TEXT | Final error message |
| `killed_at` | TIMESTAMPTZ | Time of death |
| `resurrected_at` | TIMESTAMPTZ | Set if re-enqueued via dashboard |

**`cj_schedules`** — recurring cron jobs

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

**`cj_queue_pauses`** — paused queues

| Column | Type | Description |
|---|---|---|
| `queue` | VARCHAR | Queue name |
| `paused_at` | TIMESTAMPTZ | When it was paused |
| `paused_by` | VARCHAR | Actor (dashboard user, API caller) |

---

#### Concurrency Strategy

CrazyJob uses PostgreSQL's `SELECT ... FOR UPDATE SKIP LOCKED` to safely distribute jobs across workers without any external lock manager.

The fetch-and-claim must be a **single atomic operation**. Never split this into two queries.

```sql
-- Worker fetch query — atomic CTE (fetch + claim in one statement)
WITH next_job AS (
    SELECT id FROM cj_jobs
    WHERE status IN ('enqueued', 'retrying')
      AND (run_at IS NULL OR run_at <= NOW())
      AND queue = ANY(:queues)
    ORDER BY priority ASC, created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE cj_jobs
SET
    status     = 'active',
    worker_id  = :worker_id,
    started_at = NOW(),
    attempts   = attempts + 1,
    updated_at = NOW()
FROM next_job
WHERE cj_jobs.id = next_job.id
RETURNING cj_jobs.*;
```

This CTE does four things atomically:
1. Finds the next available job (`SKIP LOCKED` — rows locked by other workers are transparently skipped)
2. Sets `status = 'active'` and `worker_id`
3. Records `started_at = NOW()`
4. **Increments `attempts` before any user code runs** — this is the queue poisoning protection

All four happen in a single `UPDATE ... RETURNING` — no application-level mutex needed.

---

### SQLite Backend

The SQLite driver (`crazyjob/backends/sqlite/driver.py`) provides a lightweight, zero-dependency backend ideal for development, testing, and single-machine deployments.

```python
from crazyjob.backends.sqlite import SQLiteDriver

backend = SQLiteDriver(database_path=":memory:")  # or "jobs.db"
```

#### Type Mapping

SQLite has no native support for several PostgreSQL types. The driver maps them as follows:

| PostgreSQL | SQLite | Notes |
|---|---|---|
| `TIMESTAMPTZ` | `TEXT` | ISO 8601 strings, parsed via `_parse_datetime()` |
| `JSONB` | `TEXT` | `json.dumps()` / `json.loads()` |
| `TEXT[]` (arrays) | `TEXT` | JSON-encoded lists |
| `ENUM` types | `TEXT CHECK(...)` | Constraint-based validation |
| `UUID` (gen_random_uuid) | `TEXT` | Python `str(uuid4())` |
| `NOW()` | `datetime('now')` | SQLite date function |
| `INTERVAL '5 minutes'` | `datetime('now', '-5 minutes')` | SQLite modifier syntax |
| `original_job->>'id'` | `json_extract(original_job, '$.id')` | SQLite JSON1 extension |

#### Concurrency Strategy (SQLite)

SQLite is single-writer. CrazyJob uses three mechanisms for safe concurrent access:

1. **`PRAGMA journal_mode=WAL`** — allows concurrent readers while a write is in progress
2. **`PRAGMA busy_timeout=5000`** — waits up to 5 seconds if the database is locked instead of failing immediately
3. **`threading.Lock`** — Python-level lock serializes all write operations

The `fetch_next` query uses `BEGIN IMMEDIATE` (exclusive write lock) + SELECT + UPDATE instead of PostgreSQL's `SELECT ... FOR UPDATE SKIP LOCKED`:

```sql
BEGIN IMMEDIATE;

SELECT * FROM cj_jobs
WHERE status IN ('enqueued', 'retrying')
  AND (run_at IS NULL OR run_at <= datetime('now'))
  AND queue IN (?, ?, ...)
ORDER BY priority ASC, created_at ASC
LIMIT 1;

UPDATE cj_jobs
SET status = 'active', worker_id = ?, started_at = datetime('now'),
    attempts = attempts + 1, updated_at = datetime('now')
WHERE id = ?;

COMMIT;
```

**Limitation:** Since SQLite serializes all writes, throughput is lower than PostgreSQL. This backend is best suited for development, testing, and single-worker deployments.

---

## Job Lifecycle

```
enqueue()
    │
    ▼
┌──────────┐
│ enqueued │ ←─────────────────────────────────────────────┐
└────┬─────┘                                               │
     │  worker picks up (fetch_next):                      │ resurrect
     │  status='active', attempts+=1,                      │ (dashboard)
     │  worker_id set, started_at set                      │
     ▼                                                     │
┌──────────┐     ┌───────────────┐                ┌───────┴──────┐
│  active  │────►│  completed ✓  │                │     dead     │
└────┬─────┘     └───────────────┘                └──────────────┘
     │                                                     ▲
     │  perform() raises                                   │ attempts >= max
     ▼                                                     │
┌──────────┐                                              │
│  failed  │─────────────────────────────────────────────►┘
└────┬─────┘
     │  attempts < max
     ▼
┌──────────┐  run_at = now + backoff
│ retrying │──────────► re-enters enqueued flow when run_at passes
└──────────┘
```

**Key:** `attempts` is incremented atomically inside `fetch_next` (at the `enqueued → active` transition), **not** at the `active → failed` transition. This ensures that even if the worker process crashes during `perform()`, the attempt is already recorded.

---

## Worker Engine

### Fetch Loop

Each worker thread runs an independent fetch loop. **`attempts` is already incremented by `fetch_next` before any user code runs** — this is the queue poisoning protection.

```python
def _run_loop(self) -> None:
    while self._running:
        job = self.backend.fetch_next(self._queues)

        if job is None:
            time.sleep(self._poll_interval)  # default: 1s, configurable
            continue

        # At this point, job.attempts has ALREADY been incremented by fetch_next.
        # If we're at or over the limit, kill immediately — don't run user code.
        if job.attempts > job.max_attempts:
            self.backend.move_to_dead(
                job.id,
                reason=f"Exceeded max_attempts ({job.max_attempts})"
            )
            continue

        self._execute(job)

def _execute(self, job: JobRecord) -> None:
    try:
        instance = self._load_job_class(job)
        self._pipeline.run(job, lambda: instance.perform(*job.args, **job.kwargs))
        self.backend.mark_completed(job.id, result={})

    except Retry as e:
        retry_at = datetime.utcnow() + timedelta(seconds=e.in_seconds or 0)
        self.backend.mark_failed(job.id, error=str(e), retry_at=retry_at)

    except Exception as e:
        error_text = traceback.format_exc()
        if job.attempts >= job.max_attempts:
            # This was the last allowed attempt — send to dead letters
            self.backend.move_to_dead(job.id, reason=error_text)
        else:
            # Still have attempts left — schedule retry with backoff
            policy = get_backoff_policy(type(instance).retry_backoff)
            retry_at = datetime.utcnow() + policy.delay_for(job.attempts)
            self.backend.mark_failed(job.id, error=error_text, retry_at=retry_at)
```

### Concurrency Model

CrazyJob uses a thread-pool model by default (one thread per concurrency slot). This works well for I/O-bound jobs (HTTP calls, database writes, emails).

```
Worker Process
├── Main Thread       (fetch loop coordinator)
├── Thread 1          (fetch loop)
├── Thread 2          (fetch loop)
├── ...
├── Thread N          (fetch loop, N = --concurrency)
└── Heartbeat Thread  (writes last_beat_at every 10s)
```

For CPU-bound jobs, workers can be started as separate processes using the `--processes` flag (uses `multiprocessing` instead of `threading`).

### Heartbeat & Dead Worker Detection

Every worker writes a heartbeat to `cj_workers.last_beat_at` every 10 seconds. A supervisor thread running inside any active worker periodically checks for stale entries:

```python
DEAD_THRESHOLD = timedelta(seconds=60)

stale_workers = SELECT * FROM cj_workers
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
4. Deregister worker from `cj_workers`
5. Exit

---

## Retry & Backoff Policies

Retry behavior is configured per job class:

```python
class MyJob(Job):
    max_attempts = 5
    retry_backoff = "exponential"   # "linear" | "exponential" | "exponential_cap" | callable
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
cj.use(LoggingMiddleware())
cj.use(SentryMiddleware(dsn="..."))

# Custom middleware
from crazyjob.core.middleware import Middleware

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

The scheduler is a separate process (`crazyjob scheduler`) that:

1. Reads all enabled entries from `cj_schedules`
2. Finds entries where `next_run_at <= NOW()`
3. Enqueues the corresponding job class
4. Updates `last_run_at` and recomputes `next_run_at` using `croniter`

Uses `SELECT ... FOR UPDATE SKIP LOCKED` on `cj_schedules` so multiple scheduler processes never double-fire the same schedule.

---

## Dashboard Internals

The dashboard is structured so that every action is a pure Python function that takes a database connection and returns data:

```python
# crazyjob/dashboard/core/queries.py

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
# crazyjob/dashboard/core/actions.py

class DashboardActions:
    def resurrect(self, dead_letter_id: str) -> str:
        """Re-enqueue a dead job. Returns new job ID."""
        ...

    def cancel(self, job_id: str) -> None:
        """Remove an enqueued job before it is picked up."""
        ...

    def pause_queue(self, queue: str) -> None: ...
    def resume_queue(self, queue: str) -> None: ...
    def clear_queue(self, queue: str) -> None: ...
    def bulk_resurrect(self) -> int:
        """Resurrect all dead letters. Returns count."""
        ...
```

The framework adapters call these functions directly from their route handlers.

### Dashboard SQL Compatibility

`DashboardQueries`, `DashboardActions`, and `DashboardMetrics` use raw SQL via `backend._cursor()`. Since PostgreSQL and SQLite have different SQL dialects, we have SQLite-specific subclasses:

| Base class (PostgreSQL) | SQLite subclass |
|---|---|
| `DashboardQueries` | `SQLiteDashboardQueries` |
| `DashboardActions` | `SQLiteDashboardActions` |
| `DashboardMetrics` | `SQLiteDashboardMetrics` |

The **factory module** (`crazyjob/dashboard/core/factory.py`) auto-detects the backend and returns the correct class:

```python
from crazyjob.dashboard.core.factory import (
    create_dashboard_queries,
    create_dashboard_actions,
    create_dashboard_metrics,
)

queries = create_dashboard_queries(backend)   # returns SQLite* if backend is SQLiteDriver
actions = create_dashboard_actions(backend)
metrics = create_dashboard_metrics(backend)
```

Both Flask and FastAPI integrations use this factory to instantiate the correct dashboard classes.

---

## Flask Integration

`FlaskCrazyJob` (`crazyjob/integrations/flask/__init__.py`) follows Flask's standard `init_app()` pattern:

```python
from crazyjob.integrations.flask import FlaskCrazyJob

cj = FlaskCrazyJob()
cj.init_app(app)
```

- **Config**: reads from `app.config["CRAZYJOB_DATABASE_URL"]`
- **Backend**: auto-detects from URL scheme (`postgresql://` or `sqlite://`)
- **Lifecycle**: `@app.teardown_appcontext` closes backend
- **Dashboard**: mounts Flask `Blueprint` at `/crazyjob/`
- **Job context**: wraps `perform()` in `with app.app_context()`

---

## FastAPI Integration

`FastAPICrazyJob` (`crazyjob/integrations/fastapi/__init__.py`) uses a settings dict instead of framework config:

```python
from fastapi import FastAPI
from crazyjob.integrations.fastapi import FastAPICrazyJob

app = FastAPI()
cj = FastAPICrazyJob(app=app, settings={"database_url": "sqlite:///jobs.db"})
```

- **Config**: reads from the `settings` dict passed to the constructor
- **Backend**: auto-detects from URL scheme (`postgresql://` or `sqlite://`)
- **Lifecycle**: `@app.on_event("shutdown")` closes backend
- **Dashboard**: mounts Starlette `APIRouter` at `/crazyjob/`; uses `Jinja2Templates` (same templates as Flask); flash messages via query params
- **Job context**: passthrough (no app context needed — FastAPI has no global request context)

The dashboard adapter (`crazyjob/dashboard/adapters/fastapi.py`) uses POST-Redirect-GET with `status_code=303` for all actions.

---

## Adding a New Framework Integration

To add support for a new framework, create a new directory under `crazyjob/integrations/` and implement `FrameworkIntegration`:

```python
# crazyjob/integrations/myframework/__init__.py

from crazyjob.integrations.base import FrameworkIntegration
from crazyjob.config import CrazyJobConfig
from crazyjob.dashboard.core.factory import create_dashboard_queries, create_dashboard_actions


class MyFrameworkCrazyJob(FrameworkIntegration):

    def get_config(self) -> CrazyJobConfig:
        # Read from your framework's config system
        ...

    def get_backend(self):
        # Use _create_backend(url) to auto-detect PostgreSQL or SQLite
        ...

    def setup_lifecycle_hooks(self, app) -> None:
        # Register startup/shutdown with your framework
        ...

    def mount_dashboard(self, app, url_prefix: str) -> None:
        queries = create_dashboard_queries(self._backend)
        actions = create_dashboard_actions(self._backend)
        # Create and mount your dashboard adapter
        ...

    def wrap_job_context(self, func):
        # Wrap in your framework's app context, if needed
        ...
```

Then create `crazyjob/dashboard/adapters/myframework.py` implementing `DashboardAdapter.get_mountable()`.

**That's all.** No changes to core, worker, retry, serializer, or scheduler.

---

## Adding a New Storage Backend

Create a new directory under `crazyjob/backends/` and implement `BackendDriver`:

```python
# crazyjob/backends/mybackend/driver.py

from crazyjob.backends.base import BackendDriver
from crazyjob.core.job import JobRecord


class MyBackendDriver(BackendDriver):

    def __init__(self, connection_url: str):
        self.conn = connect(connection_url)

    def enqueue(self, job: JobRecord) -> str:
        # Write job to your storage system
        ...

    def fetch_next(self, queues: list[str]) -> JobRecord | None:
        # Atomically fetch, lock, claim, and increment attempts
        # Must guarantee no two workers receive the same job
        ...

    # Implement remaining abstract methods...
```

Pass it to the worker:

```python
from crazyjob.backends.mybackend import MyBackendDriver
from crazyjob.core.worker import Worker

worker = Worker(
    backend=MyBackendDriver("mybackend://localhost"),
    queues=["default"],
    concurrency=10
)
```

---

## Code Quality & Linting

### Tools

CrazyJob uses a fixed, opinionated toolchain. All tools are configured to run identically in local development, pre-commit hooks, and CI — no "works on my machine" divergence.

| Tool | Role | Version pinned in |
|---|---|---|
| **Ruff** | Linter + import sorter (replaces flake8, isort, pyupgrade) | `pyproject.toml` |
| **Black** | Code formatter | `pyproject.toml` |
| **Mypy** | Static type checking | `pyproject.toml` |
| **Bandit** | Security linter (finds common vulnerabilities) | `pyproject.toml` |
| **pre-commit** | Git hook runner | `.pre-commit-config.yaml` |

### Configuration Files

**`pyproject.toml`** — single source of truth for all tool configuration:

```toml
[project]
name = "crazyjob"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "click>=8.1",
    "croniter>=2.0",
]

[project.optional-dependencies]
postgresql = ["psycopg2-binary>=2.9"]
flask = ["flask>=3.0", "psycopg2-binary>=2.9"]
fastapi = ["fastapi>=0.100", "uvicorn>=0.25", "jinja2>=3.1"]
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
    "psycopg2-binary>=2.9",
    "httpx>=0.25",
    "fastapi>=0.100",
    "uvicorn>=0.25",
    "jinja2>=3.1",
    "flask>=3.0",
]

[project.scripts]
crazyjob = "crazyjob.cli.commands:cli"

# ── Ruff ──────────────────────────────────────────────────────────────────────
[tool.ruff]
target-version = "py310"
line-length = 100

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "UP",   # pyupgrade
    "B",    # flake8-bugbear
    "C4",   # flake8-comprehensions
    "SIM",  # flake8-simplify
    "TCH",  # flake8-type-checking
    "RUF",  # ruff-specific rules
]
ignore = [
    "E501",  # line length — handled by Black
]

[tool.ruff.lint.isort]
known-first-party = ["crazyjob"]

# ── Black ─────────────────────────────────────────────────────────────────────
[tool.black]
line-length = 100
target-version = ["py310", "py311", "py312"]

# ── Mypy ──────────────────────────────────────────────────────────────────────
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

# ── Bandit ────────────────────────────────────────────────────────────────────
[tool.bandit]
exclude_dirs = ["tests"]
skips = ["B101"]  # allow assert in tests

# ── Pytest ────────────────────────────────────────────────────────────────────
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=crazyjob --cov-report=term-missing --cov-fail-under=85"
markers = [
    "unit: pure unit tests, no I/O",
    "integration: tests that require a database (PostgreSQL or SQLite)",
    "e2e: full worker lifecycle tests with real threads",
]

# ── Coverage ──────────────────────────────────────────────────────────────────
[tool.coverage.run]
source = ["crazyjob"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "@abstractmethod",
]
```

### Pre-commit Hooks

**`.pre-commit-config.yaml`** — runs automatically on every `git commit`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.4
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/psf/black
    rev: 24.4.2
    hooks:
      - id: black

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.9.0
    hooks:
      - id: mypy
        additional_dependencies: [types-psycopg2, types-croniter]

  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.8
    hooks:
      - id: bandit
        args: ["-c", "pyproject.toml"]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-merge-conflict
      - id: debug-statements
      - id: no-commit-to-branch
        args: [--branch, main]
```

Install hooks after cloning the repo:

```bash
pip install pre-commit
pre-commit install
```

### CI Lint Pipeline

```yaml
# .github/workflows/lint.yml
name: Lint

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - run: pip install ".[dev]"

      - name: Ruff (lint + import sort)
        run: ruff check . --output-format=github

      - name: Black (format check)
        run: black --check .

      - name: Mypy (type check)
        run: mypy crazyjob/

      - name: Bandit (security scan)
        run: bandit -c pyproject.toml -r crazyjob/

      # Enforce that crazyjob/core/ never imports framework packages
      - name: Import boundary check
        run: |
          python - <<'EOF'
          import ast, sys, pathlib

          FORBIDDEN = {"flask", "django", "fastapi", "sanic", "starlette"}
          errors = []

          for path in pathlib.Path("crazyjob/core").rglob("*.py"):
              tree = ast.parse(path.read_text())
              for node in ast.walk(tree):
                  if isinstance(node, (ast.Import, ast.ImportFrom)):
                      names = [a.name for a in getattr(node, "names", [])]
                      mod = getattr(node, "module", "") or ""
                      for name in [mod] + names:
                          if any(name.startswith(f) for f in FORBIDDEN):
                              errors.append(f"{path}:{node.lineno} imports '{name}'")

          if errors:
              print("Framework imports found in core layer:")
              for e in errors: print(" ", e)
              sys.exit(1)
          EOF
```

---

## Testing Strategy

### Test Layout

```
tests/
│
├── conftest.py                    # Shared fixtures (app, backend, db session, sqlite_backend)
├── factories.py                   # factory_boy factories for JobRecord, etc.
│
├── unit/                          # Pure unit tests — no I/O, no DB
│   ├── test_serializer.py
│   ├── test_retry_policies.py
│   ├── test_job_base_class.py
│   ├── test_middleware_pipeline.py
│   ├── test_config.py
│   ├── test_scheduler_cron.py
│   └── test_fastapi_integration.py    # FastAPI config, backend detection, middleware
│
├── integration/                   # Hit a real database
│   ├── test_backend_enqueue.py        # PostgreSQL enqueue tests
│   ├── test_backend_fetch_skip_locked.py
│   ├── test_backend_retry_flow.py
│   ├── test_backend_dead_letters.py
│   ├── test_dashboard_queries.py
│   ├── test_dashboard_actions.py
│   └── sqlite/                        # SQLite-specific (in-memory, no setup)
│       ├── test_sqlite_enqueue.py
│       ├── test_sqlite_fetch.py
│       ├── test_sqlite_retry_flow.py
│       ├── test_sqlite_dead_letters.py
│       ├── test_sqlite_dashboard_queries.py
│       └── test_sqlite_dashboard_actions.py
│
└── e2e/                           # Full worker lifecycle (spawns real threads)
    ├── test_worker_processes_job.py
    ├── test_worker_retry_on_failure.py
    ├── test_worker_heartbeat.py
    ├── test_worker_dead_detection.py
    ├── test_worker_graceful_shutdown.py
    └── test_scheduler_fires_cron.py
```

### Test Layers

| Layer | Speed | DB | Threads | What it proves |
|---|---|---|---|---|
| **Unit** | < 1s each | ❌ | ❌ | Logic correctness in isolation |
| **Integration (PG)** | < 5s each | ✅ real PG | ❌ | SQL queries, locking, state transitions |
| **Integration (SQLite)** | < 1s each | ✅ in-memory | ❌ | SQLite dialect, threading.Lock, type mapping |
| **E2E** | 5–30s each | ✅ real PG | ✅ real | Full worker lifecycle under real conditions |

### Unit Tests

No database, no threads. Use `unittest.mock` or `pytest-mock` to stub the `BackendDriver`.

```python
# tests/unit/test_retry_policies.py
import pytest
from datetime import timedelta
from crazyjob.core.retry import ExponentialBackoff, LinearBackoff

class TestExponentialBackoff:
    def test_first_attempt_delay(self):
        policy = ExponentialBackoff(base_seconds=15)
        assert policy.delay_for(attempt=1) == timedelta(seconds=30)

    def test_second_attempt_delay(self):
        policy = ExponentialBackoff(base_seconds=15)
        assert policy.delay_for(attempt=2) == timedelta(seconds=60)

    def test_delay_doubles_each_attempt(self):
        policy = ExponentialBackoff(base_seconds=15, jitter=False)
        delays = [policy.delay_for(i).total_seconds() for i in range(1, 6)]
        assert delays == [30, 60, 120, 240, 480]

    def test_jitter_stays_within_bounds(self):
        policy = ExponentialBackoff(base_seconds=15, jitter=True)
        for attempt in range(1, 6):
            delay = policy.delay_for(attempt).total_seconds()
            base = 15 * (2 ** attempt)
            assert base * 0.9 <= delay <= base * 1.1
```

```python
# tests/unit/test_serializer.py
import pytest
from datetime import datetime, timezone
from uuid import UUID
from crazyjob.core.serializer import Serializer

class TestSerializer:
    def test_roundtrip_primitives(self):
        data = {"name": "test", "count": 42, "active": True, "score": 3.14}
        assert Serializer.loads(Serializer.dumps(data)) == data

    def test_roundtrip_datetime(self):
        dt = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone.utc)
        result = Serializer.loads(Serializer.dumps({"ts": dt}))
        assert result["ts"] == dt

    def test_roundtrip_uuid(self):
        uid = UUID("12345678-1234-5678-1234-567812345678")
        result = Serializer.loads(Serializer.dumps({"id": uid}))
        assert result["id"] == uid

    def test_rejects_non_serializable_objects(self):
        with pytest.raises(TypeError):
            Serializer.dumps({"obj": object()})
```

```python
# tests/unit/test_middleware_pipeline.py
import pytest
from unittest.mock import MagicMock, call
from crazyjob.core.middleware import MiddlewarePipeline

def test_pipeline_calls_before_and_after_in_order():
    m1, m2 = MagicMock(), MagicMock()
    pipeline = MiddlewarePipeline([m1, m2])
    job = MagicMock()

    pipeline.run(job, lambda: None)

    assert m1.before_perform.call_args == call(job)
    assert m2.before_perform.call_args == call(job)
    assert m1.after_perform.called
    assert m2.after_perform.called

def test_pipeline_calls_on_failure_when_perform_raises():
    m = MagicMock()
    pipeline = MiddlewarePipeline([m])
    job = MagicMock()
    error = ValueError("boom")

    with pytest.raises(ValueError):
        pipeline.run(job, lambda: (_ for _ in ()).throw(error))

    m.on_failure.assert_called_once_with(job, error)
    m.after_perform.assert_not_called()
```

### Integration Tests

Spin up a real PostgreSQL instance using `pytest-postgresql`. Each test gets a clean schema.

```python
# tests/conftest.py
import pytest
from pytest_postgresql import factories
from crazyjob.backends.postgresql.driver import PostgreSQLDriver
from crazyjob.backends.postgresql.schema import apply_schema

postgresql_proc = factories.postgresql_proc(port=None)
postgresql = factories.postgresql("postgresql_proc")

@pytest.fixture()
def backend(postgresql):
    dsn = (
        f"host={postgresql.info.host} port={postgresql.info.port} "
        f"dbname={postgresql.info.dbname} user={postgresql.info.user}"
    )
    driver = PostgreSQLDriver(dsn=dsn)
    apply_schema(driver)  # create cj_* tables
    yield driver
    driver.close()
```

```python
# tests/integration/test_backend_fetch_skip_locked.py
import threading
import pytest

def test_two_workers_never_pick_same_job(backend, job_factory):
    """SKIP LOCKED must guarantee exclusive job consumption."""
    job = job_factory.enqueue(backend, queue="default")

    results = []

    def fetch():
        result = backend.fetch_next(queues=["default"])
        results.append(result)

    t1 = threading.Thread(target=fetch)
    t2 = threading.Thread(target=fetch)
    t1.start(); t2.start()
    t1.join(); t2.join()

    fetched = [r for r in results if r is not None]
    assert len(fetched) == 1, "Exactly one worker should have fetched the job"
    assert fetched[0].id == job.id


def test_enqueue_sets_correct_initial_state(backend, job_factory):
    job = job_factory.enqueue(backend, queue="mailers", kwargs={"user_id": 42})

    record = backend.get_job(job.id)
    assert record.status == "enqueued"
    assert record.attempts == 0
    assert record.kwargs == {"user_id": 42}
    assert record.started_at is None


def test_fetch_next_increments_attempts(backend, job_factory):
    """fetch_next atomically claims the job AND increments attempts."""
    job = job_factory.enqueue(backend)
    fetched = backend.fetch_next(queues=["default"])

    assert fetched is not None
    assert fetched.attempts == 1
    assert fetched.status == "active"
    assert fetched.worker_id is not None
    assert fetched.started_at is not None


def test_mark_failed_records_error(backend, job_factory):
    job = job_factory.enqueue(backend)
    backend.fetch_next(queues=["default"])  # claims + increments attempts
    backend.mark_failed(job.id, error="Something went wrong")

    record = backend.get_job(job.id)
    assert record.status == "failed"
    assert "Something went wrong" in record.error


def test_job_moves_to_dead_after_max_attempts(backend, job_factory):
    job = job_factory.enqueue(backend, max_attempts=1)

    # fetch_next increments attempts to 1 (== max_attempts)
    backend.fetch_next(queues=["default"])
    backend.move_to_dead(job.id, reason="Exhausted retries")

    record = backend.get_job(job.id)
    assert record.status == "dead"

    dead = backend.get_dead_letter(job.id)
    assert dead is not None
    assert dead.reason == "Exhausted retries"
```

### End-to-End Tests

Spin up real worker threads and assert on database state after processing.

```python
# tests/e2e/test_worker_processes_job.py
import time
import threading
import pytest
from crazyjob.core.worker import Worker

def test_worker_marks_job_completed_on_success(backend, job_factory):
    job = job_factory.enqueue(backend, class_path="tests.helpers.NoOpJob")

    worker = Worker(backend=backend, queues=["default"], concurrency=1)
    thread = threading.Thread(target=lambda: worker.run(max_jobs=1))
    thread.start()
    thread.join(timeout=10)

    record = backend.get_job(job.id)
    assert record.status == "completed"
    assert record.completed_at is not None


def test_worker_retries_failed_job(backend, job_factory):
    job = job_factory.enqueue(
        backend,
        class_path="tests.helpers.FailOnceJob",
        max_attempts=3,
    )

    worker = Worker(backend=backend, queues=["default"], concurrency=1)
    thread = threading.Thread(target=lambda: worker.run(max_jobs=2))
    thread.start()
    thread.join(timeout=20)

    record = backend.get_job(job.id)
    assert record.status == "completed"
    assert record.attempts == 2


def test_worker_graceful_shutdown_requeues_active_job(backend, job_factory):
    job = job_factory.enqueue(backend, class_path="tests.helpers.SlowJob")

    worker = Worker(backend=backend, queues=["default"], concurrency=1, shutdown_timeout=1)
    thread = threading.Thread(target=worker.run)
    thread.start()

    time.sleep(0.5)
    worker.shutdown()
    thread.join(timeout=5)

    record = backend.get_job(job.id)
    assert record.status in ("enqueued", "retrying")
```

### Running Tests

```bash
# Install dev dependencies
pip install ".[dev]"

# Run only unit tests (fast, no DB needed)
pytest tests/unit/ -m unit

# Run unit + integration (needs PostgreSQL running)
pytest tests/unit/ tests/integration/

# Run the full suite
pytest

# Run with verbose output, stop on first failure
pytest -v -x

# Run a specific file
pytest tests/integration/test_backend_fetch_skip_locked.py

# Run tests matching a name pattern
pytest -k "retry"
```

### Coverage

The project enforces a minimum coverage of **85%** (configured in `pyproject.toml`). Coverage gates per module:

| Module | Minimum |
|---|---|
| `crazyjob/core/` | 90% |
| `crazyjob/backends/postgresql/` | 88% |
| `crazyjob/dashboard/core/` | 85% |
| `crazyjob/integrations/flask/` | 80% |
| Overall | 85% |

```bash
# Run with coverage report
pytest --cov=crazyjob --cov-report=term-missing

# Generate HTML report
pytest --cov=crazyjob --cov-report=html
open htmlcov/index.html
```

---

## Docker & Docker Compose

### Dockerfile

Multi-stage build. Never runs as root.

```dockerfile
# Dockerfile

# ── Stage 1: dependencies ──────────────────────────────────────────────────────
FROM python:3.12-slim AS deps

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[flask]"


# ── Stage 2: development ───────────────────────────────────────────────────────
FROM deps AS development

RUN pip install --no-cache-dir ".[dev]"

COPY . .

RUN useradd --create-home appuser
USER appuser

CMD ["flask", "run", "--host=0.0.0.0"]


# ── Stage 3: production ────────────────────────────────────────────────────────
FROM deps AS production

COPY crazyjob/ ./crazyjob/
COPY pyproject.toml .

RUN useradd --create-home appuser
USER appuser

CMD ["crazyjob", "worker", "--all-queues", "--concurrency", "10"]
```

```bash
# Build targets
docker build --target development -t crazyjob:dev .
docker build --target production  -t crazyjob:prod .
```

### Docker Compose — Development

Mounts source code as a volume for live reload without rebuilding.

```yaml
# docker-compose.yml

services:

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: crazyjob
      POSTGRES_PASSWORD: crazyjob
      POSTGRES_DB: crazyjob_dev
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U crazyjob"]
      interval: 5s
      timeout: 3s
      retries: 10

  web:
    build:
      context: .
      target: development
    command: flask run --host=0.0.0.0 --debug
    volumes:
      - .:/app
    ports:
      - "5000:5000"
    environment:
      FLASK_APP: example/app.py
      CRAZYJOB_DATABASE_URL: postgresql://crazyjob:crazyjob@db/crazyjob_dev
    depends_on:
      db:
        condition: service_healthy

  worker:
    build:
      context: .
      target: development
    command: crazyjob worker --all-queues --concurrency 4
    volumes:
      - .:/app
    environment:
      CRAZYJOB_DATABASE_URL: postgresql://crazyjob:crazyjob@db/crazyjob_dev
    depends_on:
      db:
        condition: service_healthy

  scheduler:
    build:
      context: .
      target: development
    command: crazyjob scheduler
    volumes:
      - .:/app
    environment:
      CRAZYJOB_DATABASE_URL: postgresql://crazyjob:crazyjob@db/crazyjob_dev
    depends_on:
      db:
        condition: service_healthy

volumes:
  postgres_data:
```

Common development commands:

```bash
# Start everything
docker compose up

# Start only the database (run web/worker locally)
docker compose up db

# Apply migrations
docker compose run --rm web crazyjob migrate

# Open a psql shell
docker compose exec db psql -U crazyjob crazyjob_dev

# Tail worker logs
docker compose logs -f worker

# Run tests inside the container
docker compose run --rm web pytest tests/unit/

# Rebuild after changing dependencies
docker compose build web
```

### Docker Compose — CI

Stripped-down for GitHub Actions. No volumes, no exposed ports.

```yaml
# docker-compose.ci.yml

services:

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: crazyjob
      POSTGRES_PASSWORD: crazyjob
      POSTGRES_DB: crazyjob_test
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U crazyjob"]
      interval: 3s
      timeout: 2s
      retries: 15

  test:
    build:
      context: .
      target: development
    command: >
      sh -c "
        crazyjob migrate &&
        pytest tests/ --cov=crazyjob --cov-report=xml -p no:warnings
      "
    environment:
      CRAZYJOB_DATABASE_URL: postgresql://crazyjob:crazyjob@db/crazyjob_test
    depends_on:
      db:
        condition: service_healthy
```

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run test suite
        run: docker compose -f docker-compose.ci.yml up --abort-on-container-exit --exit-code-from test

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          files: ./coverage.xml
```

### Docker Compose — Production Reference

Reference configuration for deploying CrazyJob-backed applications.

```yaml
# docker-compose.prod.yml

services:

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: ${DB_NAME}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  web:
    image: myapp:${IMAGE_TAG:-latest}
    build:
      context: .
      target: production
    command: gunicorn "myapp:create_app()" --bind 0.0.0.0:8000 --workers 4
    environment:
      CRAZYJOB_DATABASE_URL: postgresql://${DB_USER}:${DB_PASSWORD}@db/${DB_NAME}
      SECRET_KEY: ${SECRET_KEY}
    depends_on:
      - db
    restart: unless-stopped
    ports:
      - "8000:8000"

  worker:
    image: myapp:${IMAGE_TAG:-latest}
    command: crazyjob worker --queues critical,default,mailers --concurrency 10
    environment:
      CRAZYJOB_DATABASE_URL: postgresql://${DB_USER}:${DB_PASSWORD}@db/${DB_NAME}
    depends_on:
      - db
    restart: unless-stopped
    deploy:
      replicas: 2           # scale horizontally — SKIP LOCKED handles it

  scheduler:
    image: myapp:${IMAGE_TAG:-latest}
    command: crazyjob scheduler
    environment:
      CRAZYJOB_DATABASE_URL: postgresql://${DB_USER}:${DB_PASSWORD}@db/${DB_NAME}
    depends_on:
      - db
    restart: unless-stopped
    deploy:
      replicas: 1           # always exactly 1 scheduler

volumes:
  postgres_data:
```

```bash
# Deploy with a specific image tag
IMAGE_TAG=v1.2.0 docker compose -f docker-compose.prod.yml up -d

# Scale workers up at runtime
docker compose -f docker-compose.prod.yml up -d --scale worker=5
```

---

## CI/CD Pipeline

The full pipeline runs on every push and pull request. All steps must pass before merging to `main`.

```
Push / PR
    │
    ├─► Lint job (parallel)
    │       ├── ruff check
    │       ├── black --check
    │       ├── mypy
    │       ├── bandit
    │       └── import boundary check (core must not import frameworks)
    │
    ├─► Test job (parallel)
    │       ├── docker compose -f docker-compose.ci.yml up
    │       │       ├── pytest tests/unit/
    │       │       ├── pytest tests/integration/
    │       │       └── pytest tests/e2e/
    │       └── upload coverage → Codecov
    │
    └─► (on merge to main only)
            ├── docker build --target production
            ├── docker push registry/crazyjob:sha
            └── (on git tag) publish to PyPI
```

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  lint:
    uses: ./.github/workflows/lint.yml

  test:
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run full test suite via Docker Compose
        run: docker compose -f docker-compose.ci.yml up --abort-on-container-exit --exit-code-from test
      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v4

  publish:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: [lint, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install build twine
      - run: python -m build
      - run: twine upload dist/*
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}
```

---

## Roadmap

| Phase | Milestone | Status |
|---|---|---|
| 1 | PostgreSQL schema + migrations | ✅ Done |
| 2 | `BackendDriver` + PostgreSQL driver | ✅ Done |
| 3 | Core engine (Job, Queue, Client, Serializer, Retry) | ✅ Done |
| 4 | Worker engine (fetch loop, heartbeat, shutdown) | ✅ Done |
| 5 | `FrameworkIntegration` ABC + Flask adapter | ✅ Done |
| 6 | `DashboardAdapter` ABC + dashboard core queries | ✅ Done |
| 7 | Flask dashboard adapter (Blueprint + Jinja2 templates) | ✅ Done |
| 8 | CLI (`crazyjob worker`, `crazyjob scheduler`) | ✅ Done |
| 9 | Middleware pipeline | ✅ Done |
| 10 | Lint toolchain (Ruff, Black, Mypy, Bandit, pre-commit) | ✅ Done |
| 11 | Unit + integration + E2E test suite | ✅ Done |
| 12 | Docker + Docker Compose (dev, CI, prod) | ✅ Done |
| 13 | CI/CD pipeline (GitHub Actions) | ✅ Done |
| 14 | SQLite backend | ✅ Done |
| 15 | FastAPI integration + dashboard adapter | ✅ Done |
| — | Django integration | 🔵 Future |
| — | Sanic integration | 🔵 Future |
| — | PyPI release | 🔵 Future |

---

*CrazyJob is under active development. APIs marked as stable will follow semantic versioning. Contributions welcome — please read `CONTRIBUTING.md` before opening a PR.*
