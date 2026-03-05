# CrazyJob

**Background job processing for Python web applications — PostgreSQL only, no Redis required.**

Conveyor is a framework-agnostic background job library inspired by Sidekiq and ActiveJob. Define jobs as Python classes, enqueue them from anywhere in your application, and process them with a resilient worker engine backed entirely by PostgreSQL.

```bash
pip install conveyor-jobs
```

---

## Why Conveyor?

- **Zero extra infrastructure** — uses the PostgreSQL you already have. No Redis, no RabbitMQ, no Celery broker.
- **Framework-agnostic** — works with Flask today, Django and FastAPI on the way. The core engine has zero framework imports.
- **Built-in dashboard** — a Sidekiq-style web UI included out of the box. Active jobs, retries, dead letters, workers, cron schedules — all visible and actionable.
- **Safe concurrency** — uses PostgreSQL's `SELECT ... FOR UPDATE SKIP LOCKED` so multiple workers never pick up the same job, even across machines.
- **Batteries included** — retry policies, scheduled (cron) jobs, middleware pipeline, graceful shutdown, dead worker detection.

---

## At a Glance

```python
# Define a job
from conveyor import Job

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
conveyor worker --queues mailers,default --concurrency 10

# Run the cron scheduler
conveyor scheduler
```

---

## Features

| Feature | Details |
|---|---|
| **Storage** | PostgreSQL — `SELECT ... FOR UPDATE SKIP LOCKED` |
| **Concurrency** | Thread pool (I/O-bound) or multiprocessing (CPU-bound) |
| **Retry** | Linear, exponential, exponential-capped, or custom callable |
| **Scheduling** | Cron expressions via `@schedule` decorator |
| **Dashboard** | Enqueued · Active · Retrying · Completed · Failed · Dead · Workers · Schedules |
| **Middleware** | Before/after hooks per job, with built-in Sentry and Datadog support |
| **Frameworks** | Flask ✅ · Django 🔵 · FastAPI 🔵 · Sanic 🔵 |

> 🔵 Coming soon

---

## Framework Setup (Flask)

```python
from flask import Flask
from conveyor.integrations.flask import FlaskConveyor

app = Flask(__name__)
app.config["CONVEYOR_DATABASE_URL"] = "postgresql://user:password@localhost/mydb"

conveyor = FlaskConveyor(app)
```

Apply migrations, then navigate to `/conveyor` for the dashboard.

```bash
conveyor migrate
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
- [ ] PostgreSQL backend driver
- [ ] Core engine (Job, Worker, Retry, Scheduler)
- [ ] Flask integration
- [ ] Web dashboard
- [ ] PyPI release
- [ ] Django integration
- [ ] FastAPI integration
- [ ] Redis backend driver

---

## License

MIT
