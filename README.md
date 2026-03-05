# CrazyJob

**Background job processing for Python web applications — PostgreSQL or SQLite, no Redis required.**

CrazyJob is a framework-agnostic background job library inspired by Sidekiq and ActiveJob. Define jobs as Python classes, enqueue them from anywhere in your application, and process them with a resilient worker engine backed by PostgreSQL (production) or SQLite (development).

```bash
pip install crazyjob
```

---

## Why CrazyJob?

- **Zero extra infrastructure** — uses the PostgreSQL you already have, or SQLite for local dev. No Redis, no RabbitMQ, no Celery broker.
- **Framework-agnostic** — works with Flask and FastAPI. Django on the way. The core engine has zero framework imports.
- **Built-in dashboard** — a Sidekiq-style web UI included out of the box. Active jobs, retries, dead letters, workers, cron schedules — all visible and actionable.
- **Safe concurrency** — uses PostgreSQL's `SELECT ... FOR UPDATE SKIP LOCKED` so multiple workers never pick up the same job, even across machines.
- **Batteries included** — retry policies, scheduled (cron) jobs, middleware pipeline, graceful shutdown, dead worker detection.

---

## At a Glance

```python
# Define a job
from crazyjob import Job

class SendInvoiceJob(Job):
    queue = "mailers"
    max_attempts = 5
    retry_backoff = "exponential"

    def perform(self, invoice_id: int, email: str):
        invoice = Invoice.query.get(invoice_id)
        send_email(to=email, attachment=invoice.pdf)

# Enqueue it anywhere in your app
SendInvoiceJob.enqueue(invoice_id=123, email="customer@example.com")

# Schedule for later
SendInvoiceJob.enqueue_in(timedelta(hours=2), invoice_id=123, email="customer@example.com")
```

```bash
# Run a worker
crazyjob worker --queues mailers,default --concurrency 10

# Run the cron scheduler
crazyjob scheduler
```

---

## Features

| Feature | Details |
|---|---|
| **Storage** | PostgreSQL (`SKIP LOCKED`) or SQLite (WAL mode) |
| **Concurrency** | Thread pool (I/O-bound) or multiprocessing (CPU-bound) |
| **Retry** | Linear, exponential, exponential-capped, or custom callable |
| **Scheduling** | Cron expressions via `@schedule` decorator |
| **Dashboard** | Enqueued · Active · Retrying · Completed · Failed · Dead · Workers · Schedules |
| **Middleware** | Before/after hooks per job — write custom middleware for logging, Sentry, Datadog, etc. |
| **Frameworks** | Flask ✅ · FastAPI ✅ · Django 🔵 · Sanic 🔵 |

> 🔵 Coming soon

---

## Framework Setup

### Flask

```python
from flask import Flask
from crazyjob.integrations.flask import FlaskCrazyJob

app = Flask(__name__)
app.config["CRAZYJOB_DATABASE_URL"] = "postgresql://user:password@localhost/mydb"

cj = FlaskCrazyJob(app)
```

### FastAPI

```python
from fastapi import FastAPI
from crazyjob.integrations.fastapi import FastAPICrazyJob

app = FastAPI()
cj = FastAPICrazyJob(app, settings={
    "database_url": "postgresql://user:password@localhost/mydb",
})
```

Apply migrations, then navigate to `/crazyjob` for the dashboard.

```bash
crazyjob migrate
```

---

## Documentation

| Document | Description |
|---|---|
| [**User Guide**](https://github.com/juniortada/crazy_job/blob/main/USER_GUIDE.md) | How to install, configure, define jobs, enqueue, retry, schedule, run workers, use the dashboard, write middleware, and practical examples |
| [**Architecture**](https://github.com/juniortada/crazy_job/blob/main/ARCHITECTURE.md) | Internal layer design, abstract interfaces (`BackendDriver`, `FrameworkIntegration`, `DashboardAdapter`), PostgreSQL schema, worker internals, and guides for adding new frameworks or storage backends |

---

## Roadmap

- [x] Architecture & design
- [x] PostgreSQL backend driver
- [x] Core engine (Job, Worker, Retry, Scheduler)
- [x] Flask integration
- [x] Web dashboard
- [x] Lint toolchain + test suite
- [x] Docker & Docker Compose
- [x] CI/CD pipeline
- [x] SQLite backend driver
- [x] FastAPI integration
- [ ] PyPI release
- [ ] Django integration

---

## License

MIT
