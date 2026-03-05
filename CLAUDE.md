# CLAUDE.md — CrazyJob Project Instructions

This file is the single source of truth for Claude when working on this codebase.
Read it entirely before writing any code, creating any file, or suggesting any change.

---

## Project Identity

- **Name:** CrazyJob
- **PyPI package:** `crazyjob`
- **CLI command:** `crazyjob`
- **Python package root:** `crazyjob/`
- **Description:** Framework-agnostic background job processing for Python web apps, backed exclusively by PostgreSQL.
- **Inspiration:** Sidekiq / ActiveJob (Ruby on Rails)
- **No Redis.** No Celery. No RabbitMQ. PostgreSQL is the only required infrastructure.

---

## Language & Tooling

- **Python 3.10+** — use `match`, `|` union types, `list[str]` (not `List[str]`), `str | None` (not `Optional[str]`)
- **Type hints everywhere** — all public functions and methods must be fully annotated
- **Formatter:** Black, line length 100
- **Linter:** Ruff (replaces flake8 + isort + pyupgrade)
- **Type checker:** Mypy in strict mode
- **Security scanner:** Bandit
- **Test framework:** pytest
- **Factories:** factory_boy
- **DB fixtures:** pytest-postgresql

Never use `Optional[X]` — write `X | None`. Never use `List[X]` or `Dict[K, V]` — write `list[X]` or `dict[K, V]`.

---

## The Four-Layer Rule — CRITICAL

CrazyJob is structured in four strict layers. **Never violate layer boundaries.**

```
Layer 3 — Framework Integrations  (crazyjob/integrations/)
Layer 2 — Dashboard               (crazyjob/dashboard/)
Layer 1 — Core Engine             (crazyjob/core/)
Layer 0 — Storage Backends        (crazyjob/backends/)
```

### Rules

| Layer | Can import from | Cannot import from |
|---|---|---|
| `core/` | `backends/base.py`, stdlib only | Flask, Django, FastAPI, Sanic, any framework |
| `backends/` | stdlib, psycopg2 only | `core/`, any framework |
| `dashboard/core/` | `backends/base.py`, `core/` | Any HTTP framework |
| `dashboard/adapters/` | `dashboard/core/`, framework of choice | Other framework adapters |
| `integrations/` | All layers | Other integrations |

If you are writing code in `crazyjob/core/` or `crazyjob/backends/` and you find yourself importing `flask`, `django`, `fastapi`, or `sanic` — **stop**. You are in the wrong layer.

---

## Full Directory Structure

```
crazyjob/
├── __init__.py                    # Public API: Job, schedule, CrazyJobError
├── config.py                      # CrazyJobConfig dataclass
│
├── core/                          # Layer 1 — pure Python, zero framework imports
│   ├── __init__.py
│   ├── job.py                     # Base Job class + JobRecord dataclass
│   ├── queue.py                   # Queue abstraction
│   ├── worker.py                  # Worker engine (fetch loop, thread pool)
│   ├── scheduler.py               # Cron job runner
│   ├── client.py                  # Client.enqueue() — talks to BackendDriver
│   ├── serializer.py              # JSON serialization (datetime, UUID support)
│   ├── retry.py                   # LinearBackoff, ExponentialBackoff, ExponentialCapBackoff
│   ├── middleware.py              # Middleware ABC + MiddlewarePipeline
│   └── exceptions.py             # CrazyJobError, JobFailed, DeadJob, Retry
│
├── backends/
│   ├── base.py                    # BackendDriver ABC — the only interface core uses
│   └── postgresql/
│       ├── __init__.py
│       ├── driver.py              # PostgreSQLDriver implements BackendDriver
│       ├── schema.py              # apply_schema() creates cj_* tables
│       └── migrations/
│           └── 001_initial.sql    # Raw SQL migration
│
├── dashboard/
│   ├── core/                      # Pure logic — no HTTP, no framework
│   │   ├── __init__.py
│   │   ├── queries.py             # DashboardQueries class
│   │   ├── metrics.py             # Throughput, latency, error rate calculations
│   │   └── actions.py            # DashboardActions: resurrect, cancel, pause, clear
│   └── adapters/
│       ├── base.py                # DashboardAdapter ABC
│       ├── flask.py               # Flask Blueprint + Jinja2 + HTMX
│       ├── django.py              # (future) urls + views
│       ├── fastapi.py             # (future) APIRouter
│       └── sanic.py               # (future) Blueprint
│
├── integrations/
│   ├── base.py                    # FrameworkIntegration ABC — 5 abstract methods
│   ├── flask/
│   │   ├── __init__.py            # FlaskCrazyJob — init_app pattern
│   │   └── context.py             # App context, teardown, config reader
│   ├── django/                    # (future)
│   ├── fastapi/                   # (future)
│   └── sanic/                     # (future)
│
├── cli/
│   ├── __init__.py
│   └── commands.py                # Click: crazyjob worker / scheduler / migrate / purge
│
tests/
├── conftest.py                    # postgresql fixture, backend fixture, job_factory
├── factories.py                   # factory_boy: JobRecordFactory, WorkerRecordFactory
├── helpers/                       # NoOpJob, FailOnceJob, SlowJob for E2E tests
│   └── jobs.py
├── unit/
│   ├── test_serializer.py
│   ├── test_retry_policies.py
│   ├── test_job_base_class.py
│   ├── test_middleware_pipeline.py
│   ├── test_config.py
│   └── test_scheduler_cron.py
├── integration/
│   ├── test_backend_enqueue.py
│   ├── test_backend_fetch_skip_locked.py
│   ├── test_backend_retry_flow.py
│   ├── test_backend_dead_letters.py
│   ├── test_dashboard_queries.py
│   └── test_dashboard_actions.py
└── e2e/
    ├── test_worker_processes_job.py
    ├── test_worker_retry_on_failure.py
    ├── test_worker_heartbeat.py
    ├── test_worker_dead_detection.py
    ├── test_worker_graceful_shutdown.py
    └── test_scheduler_fires_cron.py
```

---

## Database Tables

All tables use the prefix `cj_`. Never use a different prefix.

| Table | Purpose |
|---|---|
| `cj_jobs` | Primary jobs table |
| `cj_workers` | Active worker registry + heartbeat |
| `cj_dead_letters` | Jobs that exhausted all attempts |
| `cj_schedules` | Recurring cron job definitions |
| `cj_queue_pauses` | Paused queue records |

### Job status ENUM values

`enqueued` | `active` | `completed` | `failed` | `dead` | `scheduled` | `retrying`

Never use any other status string.

### Concurrency mechanism

Always use `SELECT ... FOR UPDATE SKIP LOCKED` when fetching jobs. Never use application-level locks, advisory locks, or any other mechanism. This is the single most important correctness guarantee.

```sql
SELECT * FROM cj_jobs
WHERE status IN ('enqueued', 'retrying')
  AND (run_at IS NULL OR run_at <= NOW())
  AND queue = ANY(:queues)
ORDER BY priority ASC, created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;
```

---

## Queue Poisoning — Critical Protection Rules

**Queue poisoning** is what happens when a buggy job blocks the entire queue. A worker picks up the job, crashes or loops, the job goes back to `enqueued`, the next worker picks it up again — and the queue halts completely. This happened in production at a company with a hand-rolled Redis queue and caused a full-day outage.

CrazyJob prevents this with the following hard rules. **Never relax any of these.**

### Rule 1: `attempts` and `max_attempts` are NOT NULL at the database level

Both columns must have `NOT NULL` with a `DEFAULT` and a `CHECK` constraint. A job that somehow bypasses the application layer and lands in the DB without these values must be rejected by the database itself.

```sql
-- Non-negotiable schema constraints
attempts     INTEGER NOT NULL DEFAULT 0,
max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts >= 1)
```

`max_attempts = 0` is **forbidden**. Zero means infinite retries, which means one buggy job poisons the queue forever.

### Rule 2: `attempts` is incremented BEFORE `perform()` is called

The worker must write `attempts = attempts + 1` and `started_at = NOW()` to the database **before** calling `perform()`, not after. This is the single most important ordering rule in the entire codebase.

**Why:** If `perform()` causes a segfault, an OOM kill, an unhandled signal, or any crash that prevents the worker from running post-execution code — the attempt is still recorded. Without this, a crashing job resets to `attempts = 0` on every pick-up and loops forever.

```python
# CORRECT order inside the fetch loop
def _execute(self, job: JobRecord) -> None:
    # 1. Record the attempt FIRST — before any user code runs
    self.backend.increment_attempts(job.id, worker_id=self.id)  # attempts += 1, started_at = NOW()

    # 2. Check if we have already exceeded max_attempts after incrementing
    if job.attempts + 1 > job.max_attempts:
        self.backend.move_to_dead(job.id, reason="Exceeded max_attempts")
        return

    # 3. Only now run user code
    try:
        self._run_perform(job)
        self.backend.mark_completed(job.id, result={})
    except Exception as e:
        self._handle_failure(job, e)
```

### Rule 3: Every job pick-up must be visible in the database

There must be no such thing as a "silent" job execution. The moment a worker picks up a job, the following fields must be written atomically in the same transaction as the SKIP LOCKED fetch:

- `status` → `'active'`
- `worker_id` → the worker's ID
- `started_at` → `NOW()`
- `attempts` → `attempts + 1`

All four in one `UPDATE ... RETURNING`. Never split this across two queries.

```sql
-- The fetch-and-claim must be a single atomic operation
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

### Rule 4: Validate `max_attempts >= 1` at enqueue time, not just at the DB level

Defense in depth. The `Client.enqueue()` method must raise `ConfigurationError` before touching the database if `max_attempts < 1`.

```python
def enqueue(self, job_class: type[Job], ...) -> str:
    if job_class.max_attempts < 1:
        raise ConfigurationError(
            f"{job_class.__name__}.max_attempts must be >= 1. "
            f"Got {job_class.max_attempts}. "
            f"Setting max_attempts=0 would cause a poison pill that loops forever."
        )
    ...
```

### Rule 5: Dead letter is the end of the line, not a retry

When `attempts >= max_attempts`, the job moves to `cj_dead_letters` and its `status` is set to `'dead'`. It stays there until a human explicitly resurrects it from the dashboard. **Never automatically re-enqueue dead jobs.**

### Summary table

| Scenario | What happens | Queue blocked? |
|---|---|---|
| `perform()` raises an exception | `attempts += 1`, scheduled for retry if `attempts < max_attempts` | No |
| `perform()` raises and `attempts == max_attempts` | Moved to `cj_dead_letters` | No |
| Worker process crashes mid-execution | `started_at` and `attempts` already written. Dead worker detection re-enqueues if `attempts < max_attempts`, or kills if at limit | No |
| Job with `max_attempts = 0` | **Rejected at enqueue time by application. Rejected at DB level by CHECK constraint.** | Never reaches queue |
| Job with `max_attempts = NULL` | **Rejected at DB level by NOT NULL constraint.** | Never reaches queue |

---

## Abstract Interfaces — Implement These Exactly

### BackendDriver (`crazyjob/backends/base.py`)

```python
class BackendDriver(ABC):
    @abstractmethod
    def enqueue(self, job: JobRecord) -> str: ...
    @abstractmethod
    def fetch_next(self, queues: list[str]) -> JobRecord | None:
        """
        Atomically fetch, lock, and claim the next job.
        Must increment attempts and set started_at in the SAME transaction.
        Never split this into two queries. See Queue Poisoning rules.
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

### FrameworkIntegration (`crazyjob/integrations/base.py`)

```python
class FrameworkIntegration(ABC):
    @abstractmethod
    def get_config(self) -> CrazyJobConfig: ...
    @abstractmethod
    def get_backend(self) -> BackendDriver: ...
    @abstractmethod
    def setup_lifecycle_hooks(self, app: Any) -> None: ...
    @abstractmethod
    def mount_dashboard(self, app: Any, url_prefix: str) -> None: ...
    @abstractmethod
    def wrap_job_context(self, func: Callable) -> Callable: ...
```

### DashboardAdapter (`crazyjob/dashboard/adapters/base.py`)

```python
class DashboardAdapter(ABC):
    def __init__(self, queries: DashboardQueries, actions: DashboardActions) -> None:
        self.q = queries
        self.a = actions

    @abstractmethod
    def get_mountable(self) -> Any: ...
```

---

## Config Keys

All configuration keys start with `CRAZYJOB_`. When reading from Flask's `app.config`, always use these exact strings:

```
CRAZYJOB_DATABASE_URL          (required)
CRAZYJOB_QUEUES                (default: ["default"])
CRAZYJOB_DEFAULT_MAX_ATTEMPTS  (default: 3)
CRAZYJOB_DEFAULT_BACKOFF       (default: "exponential")
CRAZYJOB_POLL_INTERVAL         (default: 1.0)
CRAZYJOB_JOB_TIMEOUT           (default: None)
CRAZYJOB_DEAD_LETTER_TTL_DAYS  (default: 30)
CRAZYJOB_DASHBOARD_ENABLED     (default: True)
CRAZYJOB_DASHBOARD_PREFIX      (default: "/crazyjob")
CRAZYJOB_DASHBOARD_AUTH        (default: None)
CRAZYJOB_USE_SQLALCHEMY        (default: False)
CRAZYJOB_HEARTBEAT_INTERVAL    (default: 10)
CRAZYJOB_DEAD_WORKER_THRESHOLD (default: 60)
```

---

## Public API (`crazyjob/__init__.py`)

What a user should be able to import from the top-level package:

```python
from crazyjob import Job          # base class for all jobs
from crazyjob import schedule     # decorator for cron jobs
from crazyjob import CrazyJobError, JobFailed, DeadJob, Retry  # exceptions
```

---

## Retry Policies (`crazyjob/core/retry.py`)

Three built-in classes, one factory function:

- `LinearBackoff(base_seconds=30, jitter=True)`
- `ExponentialBackoff(base_seconds=15, jitter=True)`
- `ExponentialCapBackoff(base_seconds=15, cap_seconds=3600, jitter=True)`
- `get_backoff_policy(name: str) -> BackoffPolicy` — resolves string name to class

String aliases: `"linear"`, `"exponential"`, `"exponential_cap"`

Custom policies: any `Callable[[int], timedelta]` is accepted as `retry_backoff`.

---

## Worker Architecture (`crazyjob/core/worker.py`)

- One process, N threads (thread pool). N = `--concurrency` flag.
- One additional heartbeat thread that writes every `CRAZYJOB_HEARTBEAT_INTERVAL` seconds.
- Fetch loop per thread: `fetch_next` (atomically claims + increments attempts) → check if attempts exceeded → execute → `mark_completed/failed`.
- **`attempts` is incremented inside `fetch_next`, before user code runs.** This is non-negotiable. See Queue Poisoning rules.
- Graceful shutdown on `SIGTERM`/`SIGINT`: stop fetching, wait up to `shutdown_timeout`, re-enqueue stranded jobs (if under max_attempts), kill them (if at max_attempts), deregister.
- Dead worker detection: any worker thread that sees `last_beat_at` older than `CRAZYJOB_DEAD_WORKER_THRESHOLD` seconds re-enqueues the dead worker's active jobs if under `max_attempts`, or moves them to dead letters if at limit.

---

## Serialization Rules (`crazyjob/core/serializer.py`)

`perform()` arguments must serialize cleanly to JSONB. Supported types beyond JSON primitives:
- `datetime` → ISO 8601 string with `__type__: "datetime"` marker
- `UUID` → string with `__type__: "uuid"` marker
- Anything else → raise `TypeError` immediately at enqueue time, not at execution time

---

## Dashboard Pages & Routes (Flask)

All routes are mounted under `CRAZYJOB_DASHBOARD_PREFIX` (default `/crazyjob`).

| Route | Template | Data source |
|---|---|---|
| `GET /` | `overview.html` | `DashboardQueries.overview_stats()` |
| `GET /queues` | `queues.html` | `DashboardQueries.list_jobs(status="enqueued")` |
| `GET /active` | `active.html` | `DashboardQueries.list_jobs(status="active")` |
| `GET /scheduled` | `scheduled.html` | `DashboardQueries.list_jobs(status="scheduled")` |
| `GET /retrying` | `retrying.html` | `DashboardQueries.list_jobs(status="retrying")` |
| `GET /completed` | `completed.html` | `DashboardQueries.list_jobs(status="completed")` |
| `GET /failed` | `failed.html` | `DashboardQueries.list_jobs(status="failed")` |
| `GET /dead` | `dead.html` | `DashboardQueries.list_dead_letters()` |
| `GET /workers` | `workers.html` | `DashboardQueries.list_workers()` |
| `GET /schedules` | `schedules.html` | `DashboardQueries.list_schedules()` |
| `POST /dead/<id>/resurrect` | redirect | `DashboardActions.resurrect()` |
| `POST /jobs/<id>/cancel` | redirect | `DashboardActions.cancel()` |
| `POST /queues/<name>/pause` | redirect | `DashboardActions.pause_queue()` |
| `POST /queues/<name>/resume` | redirect | `DashboardActions.resume_queue()` |
| `POST /queues/<name>/clear` | redirect | `DashboardActions.clear_queue()` |
| `POST /dead/resurrect-all` | redirect | `DashboardActions.bulk_resurrect()` |
| `POST /schedules/<id>/trigger` | redirect | `DashboardActions.trigger_schedule()` |

Dashboard frontend stack: **Jinja2 + HTMX + Tailwind CSS (CDN)**. No Node.js, no build step.

---

## CLI Commands (`crazyjob/cli/commands.py`)

All implemented with Click.

```
crazyjob worker     --queues TEXT  --all-queues  --concurrency INT  --processes INT
                    --poll-interval FLOAT  --shutdown-timeout INT
crazyjob scheduler
crazyjob migrate    --database-url TEXT  (creates cj_* tables)
crazyjob purge      --status TEXT  --older-than TEXT  (e.g. "30d")
```

---

## Testing Rules

### File naming
- Unit tests: `tests/unit/test_<module>.py`
- Integration tests: `tests/integration/test_<what_is_being_tested>.py`
- E2E tests: `tests/e2e/test_worker_<scenario>.py`

### Markers
Always mark tests with the correct pytest marker:
```python
@pytest.mark.unit
@pytest.mark.integration
@pytest.mark.e2e
```

### The backend fixture
Integration and E2E tests receive a `backend` fixture from `conftest.py` that:
1. Spins up a temporary PostgreSQL instance via `pytest-postgresql`
2. Runs `apply_schema()` to create all `cj_*` tables
3. Yields the `PostgreSQLDriver` instance
4. Tears down after the test

### Never mock the database in integration tests
In `tests/integration/`, always use the real `backend` fixture. Mocks are only for `tests/unit/`.

### Coverage minimums (enforced via pyproject.toml)
- `crazyjob/core/` → 90%
- `crazyjob/backends/postgresql/` → 88%
- `crazyjob/dashboard/core/` → 85%
- `crazyjob/integrations/flask/` → 80%
- Overall → 85%

---

## Code Style Conventions

### Dataclasses over dicts for internal models

```python
# Good
@dataclass
class JobRecord:
    id: str
    queue: str
    class_path: str
    args: list
    kwargs: dict
    status: str
    priority: int
    attempts: int
    max_attempts: int
    run_at: datetime | None
    created_at: datetime
    ...

# Bad — never pass raw dicts around between layers
def enqueue(self, job: dict) -> str: ...
```

### Exceptions

Define all exceptions in `crazyjob/core/exceptions.py`. Never raise bare `Exception`. Use the hierarchy:

```
CrazyJobError
├── JobFailed(job_id, error)
├── DeadJob(job_id, reason)
├── Retry(in_seconds=None, reason=None)   ← raised inside perform() to force retry
└── ConfigurationError(message)
```

### Logging

Use the standard library `logging` module. Logger names follow the module path:

```python
import logging
logger = logging.getLogger(__name__)
# Results in: crazyjob.core.worker, crazyjob.backends.postgresql.driver, etc.
```

Never use `print()` in library code.

---

## Docker & Environment

### Environment variables for local development
When running via Docker Compose, these env vars are always set:
```
CRAZYJOB_DATABASE_URL=postgresql://crazyjob:crazyjob@db/crazyjob_dev
FLASK_APP=example/app.py
```

### Docker Compose services
- `db` — PostgreSQL 16
- `web` — Flask app (`flask run --debug`)
- `worker` — `crazyjob worker --all-queues --concurrency 4`
- `scheduler` — `crazyjob scheduler`

### Build targets
- `development` — includes `.[dev]`, mounts source as volume
- `production` — minimal image, runs as non-root `appuser`

---

## What Is NOT in Scope

These are explicitly out of scope. Do not implement, suggest, or plan for them:

- ❌ Redis backend
- ❌ Any broker other than PostgreSQL (SQS, RabbitMQ, etc.)
- ❌ Native `async def perform()` support
- ❌ A separate frontend application for the dashboard (must use Jinja2 + HTMX)
- ❌ Multi-tenant job isolation (single database, single schema)
- ❌ Job result storage beyond pass/fail status

---

## Implementation Order

When asked to start implementing, follow this sequence. Do not skip phases.

| Phase | What to build | Key files |
|---|---|---|
| 1 | Database schema | `backends/postgresql/migrations/001_initial.sql`, `backends/postgresql/schema.py` |
| 2 | BackendDriver ABC | `backends/base.py` |
| 3 | PostgreSQL driver | `backends/postgresql/driver.py` |
| 4 | Core models | `core/job.py` (JobRecord, WorkerRecord, DeadLetterRecord) |
| 5 | Serializer | `core/serializer.py` |
| 6 | Retry policies | `core/retry.py` |
| 7 | Exceptions | `core/exceptions.py` |
| 8 | Middleware | `core/middleware.py` |
| 9 | Client (enqueue) | `core/client.py` |
| 10 | Worker engine | `core/worker.py` |
| 11 | Scheduler | `core/scheduler.py` |
| 12 | Config | `config.py` |
| 13 | FrameworkIntegration ABC | `integrations/base.py` |
| 14 | Flask integration | `integrations/flask/__init__.py`, `integrations/flask/context.py` |
| 15 | Dashboard logic | `dashboard/core/queries.py`, `dashboard/core/actions.py`, `dashboard/core/metrics.py` |
| 16 | DashboardAdapter ABC | `dashboard/adapters/base.py` |
| 17 | Flask dashboard | `dashboard/adapters/flask.py` + templates |
| 18 | CLI | `cli/commands.py` |
| 19 | Public API | `__init__.py` |
| 20 | Unit tests | `tests/unit/` |
| 21 | Integration tests | `tests/integration/` |
| 22 | E2E tests | `tests/e2e/` |
| 23 | pyproject.toml | Full tool config (Ruff, Black, Mypy, Bandit, pytest) |
| 24 | Docker | `Dockerfile`, `docker-compose.yml`, `docker-compose.ci.yml` |
| 25 | CI | `.github/workflows/ci.yml`, `.github/workflows/lint.yml` |

---

## Reference Documents

For full details on any section, see:
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — layer design, schema, worker internals, testing strategy, Docker, CI/CD
- [`USER_GUIDE.md`](./USER_GUIDE.md) — public API, job definition, enqueueing, dashboard, middleware, examples
