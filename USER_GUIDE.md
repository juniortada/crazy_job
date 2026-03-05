# CrazyJob — User Guide

> Background job processing for Python web applications. PostgreSQL only. No Redis required.

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Framework Setup](#framework-setup)
  - [Flask](#flask)
  - [Django](#django) *(coming soon)*
  - [FastAPI](#fastapi) *(coming soon)*
- [Defining Jobs](#defining-jobs)
  - [Basic Job](#basic-job)
  - [Job Options Reference](#job-options-reference)
- [Enqueueing Jobs](#enqueueing-jobs)
  - [Enqueue Now](#enqueue-now)
  - [Enqueue With Delay](#enqueue-with-delay)
  - [Enqueue at a Specific Time](#enqueue-at-a-specific-time)
- [Queues](#queues)
  - [Defining Queues](#defining-queues)
  - [Priority](#priority)
- [Retry Policies](#retry-policies)
  - [Built-in Strategies](#built-in-strategies)
  - [Custom Retry Logic](#custom-retry-logic)
  - [Disabling Retries](#disabling-retries)
  - [Manually Retrying from Within perform()](#manually-retrying-from-within-perform)
- [Scheduled (Cron) Jobs](#scheduled-cron-jobs)
- [Running Workers](#running-workers)
  - [Basic Usage](#basic-usage)
  - [CLI Options](#cli-options)
  - [Running in Production](#running-in-production)
- [Dashboard](#dashboard)
  - [Enabling the Dashboard](#enabling-the-dashboard)
  - [Dashboard Features](#dashboard-features)
  - [Securing the Dashboard](#securing-the-dashboard)
- [Middleware](#middleware)
  - [Built-in Middleware](#built-in-middleware)
  - [Writing Custom Middleware](#writing-custom-middleware)
- [Configuration Reference](#configuration-reference)
- [Practical Examples](#practical-examples)
  - [Sending Emails](#sending-emails)
  - [Processing File Uploads](#processing-file-uploads)
  - [Sending Webhooks with Retry](#sending-webhooks-with-retry)
  - [Generating Reports](#generating-reports)
  - [Chaining Jobs](#chaining-jobs)
  - [Batch Operations](#batch-operations)
- [Testing](#testing)
- [Error Handling & Monitoring](#error-handling--monitoring)
- [FAQ](#faq)

---

## Installation

**Requirements:**
- Python 3.10+
- PostgreSQL 12+
- A Flask, Django, FastAPI, or Sanic application

```bash
pip install crazyjob
```

**With optional extras:**

```bash
pip install "crazyjob[flask]"       # Flask integration
pip install "crazyjob[django]"      # Django integration (coming soon)
pip install "crazyjob[fastapi]"     # FastAPI integration (coming soon)
```

---

## Quick Start

The fastest way to get CrazyJob running in a Flask app.

**1. Install**

```bash
pip install "crazyjob[flask]"
```

**2. Configure and initialize**

```python
# app.py
from flask import Flask
from crazyjob.integrations.flask import FlaskCrazyJob

app = Flask(__name__)
app.config["CRAZYJOB_DATABASE_URL"] = "postgresql://user:password@localhost/mydb"

cj = FlaskCrazyJob(app)
```

**3. Define a job**

```python
# jobs/email_jobs.py
from crazyjob import Job

class WelcomeEmailJob(Job):
    queue = "mailers"

    def perform(self, user_id: int):
        user = User.query.get(user_id)
        send_welcome_email(user.email)
```

**4. Enqueue it**

```python
from jobs.email_jobs import WelcomeEmailJob

@app.route("/register", methods=["POST"])
def register():
    user = create_user(request.json)
    WelcomeEmailJob.enqueue(user_id=user.id)
    return jsonify({"status": "ok"}), 201
```

**5. Create the database tables**

```bash
crazyjob migrate
```

**6. Start a worker**

```bash
crazyjob worker --queues mailers,default
```

**7. Open the dashboard**

```
http://localhost:5000/crazyjob
```

---

## Framework Setup

### Flask

#### Basic setup

```python
# app.py
from flask import Flask
from crazyjob.integrations.flask import FlaskCrazyJob

app = Flask(__name__)
app.config.update(
    CRAZYJOB_DATABASE_URL="postgresql://user:password@localhost/mydb",
    CRAZYJOB_QUEUES=["critical", "default", "low"],
    CRAZYJOB_DEFAULT_MAX_ATTEMPTS=3,
    CRAZYJOB_DASHBOARD_ENABLED=True,
    CRAZYJOB_DASHBOARD_PREFIX="/crazyjob",
)

cj = FlaskCrazyJob(app)
```

#### With application factory pattern

```python
# extensions.py
from crazyjob.integrations.flask import FlaskCrazyJob
cj = FlaskCrazyJob()

# app.py
from flask import Flask
from extensions import cj

def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(config or "config.DevelopmentConfig")

    cj.init_app(app)
    # ... other extensions

    return app
```

#### Using an existing SQLAlchemy connection

If your app already uses SQLAlchemy, CrazyJob can share the same connection pool:

```python
app.config["CRAZYJOB_USE_SQLALCHEMY"] = True  # reuses SQLALCHEMY_DATABASE_URI
```

---

### Django

> **Coming soon.** The Django integration is on the roadmap. The configuration will look like:

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "crazyjob.integrations.django",
]

CRAZYJOB = {
    "DATABASE_URL": "postgresql://user:password@localhost/mydb",
    "QUEUES": ["critical", "default", "low"],
    "DASHBOARD_ENABLED": True,
    "DASHBOARD_PREFIX": "/crazyjob",
}

# urls.py
from django.urls import path, include
urlpatterns = [
    path("crazyjob/", include("crazyjob.dashboard.adapters.django.urls")),
]
```

---

### FastAPI

> **Coming soon.** The FastAPI integration is on the roadmap. The configuration will look like:

```python
# main.py
from fastapi import FastAPI
from crazyjob.integrations.fastapi import FastAPICrazyJob

app = FastAPI()
cj = FastAPICrazyJob(
    database_url="postgresql://user:password@localhost/mydb",
    queues=["default"],
)
cj.init_app(app)
```

---

## Defining Jobs

### Basic Job

Every job is a class that inherits from `crazyjob.Job` and implements a `perform()` method.

```python
from crazyjob import Job

class SendInvoiceJob(Job):
    queue = "mailers"

    def perform(self, invoice_id: int, email: str):
        invoice = Invoice.query.get(invoice_id)
        send_email(to=email, attachment=invoice.pdf)
```

**Rules for `perform()` arguments:**
- Use only JSON-serializable types: `str`, `int`, `float`, `bool`, `list`, `dict`, `None`
- `datetime` and `UUID` objects are automatically serialized and deserialized
- Do not pass ORM model instances — pass IDs and re-fetch inside `perform()`

```python
# ✅ Good — pass the ID
UserReportJob.enqueue(user_id=user.id)

# ❌ Bad — model instances are not safely serializable
UserReportJob.enqueue(user=user)
```

### Job Options Reference

```python
from crazyjob import Job
from datetime import timedelta

class MyJob(Job):
    # Queue this job runs in (default: "default")
    queue = "critical"

    # Maximum execution attempts before moving to dead letters (default: 3)
    max_attempts = 5

    # Retry backoff strategy: "linear", "exponential", "exponential_cap", or a callable
    retry_backoff = "exponential"

    # Add ±10% jitter to retry delays to avoid thundering herd (default: True)
    retry_jitter = True

    # Job-level execution timeout (default: None — no timeout)
    timeout = timedelta(minutes=10)

    # Priority: 0 = highest, 100 = lowest (default: 50)
    priority = 10

    def perform(self, ...):
        ...
```

---

## Enqueueing Jobs

### Enqueue Now

```python
# With keyword arguments (recommended)
SendInvoiceJob.enqueue(invoice_id=123, email="user@example.com")

# With positional arguments
SendInvoiceJob.enqueue(123, "user@example.com")

# Capture the job ID
job_id = SendInvoiceJob.enqueue(invoice_id=123, email="user@example.com")
print(f"Enqueued job {job_id}")
```

### Enqueue With Delay

```python
from datetime import timedelta

# Run 30 minutes from now
SendInvoiceJob.enqueue_in(timedelta(minutes=30), invoice_id=123, email="user@example.com")

# Run in 2 hours
SendInvoiceJob.enqueue_in(timedelta(hours=2), invoice_id=123, email="user@example.com")

# Run tomorrow
SendInvoiceJob.enqueue_in(timedelta(days=1), invoice_id=123, email="user@example.com")
```

### Enqueue at a Specific Time

```python
from datetime import datetime, timezone

run_time = datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc)
SendInvoiceJob.enqueue_at(run_time, invoice_id=123, email="user@example.com")
```

---

## Queues

### Defining Queues

Queues are just strings. You don't need to register them in advance — a queue is created the moment a job is enqueued to it.

```python
class CriticalJob(Job):
    queue = "critical"

class MailerJob(Job):
    queue = "mailers"

class ReportJob(Job):
    queue = "reports"
```

Workers specify which queues they consume:

```bash
# Only consume critical and mailers
crazyjob worker --queues critical,mailers

# Consume all queues
crazyjob worker --all-queues
```

When a worker is assigned multiple queues, it checks them in order — queues listed first are polled first, giving them higher throughput.

### Priority

Jobs within the same queue can have a numeric priority. Lower numbers are processed first.

```python
class UrgentJob(Job):
    queue = "default"
    priority = 0    # processed first

class BackgroundJob(Job):
    queue = "default"
    priority = 100  # processed last
```

---

## Retry Policies

### Built-in Strategies

```python
class MyJob(Job):
    max_attempts = 5
    retry_backoff = "exponential"
```

| Strategy | Delays for attempts 1 through 5 |
|---|---|
| `"linear"` | 30s → 1m → 1.5m → 2m → 2.5m |
| `"exponential"` | 30s → 1m → 2m → 4m → 8m |
| `"exponential_cap"` | 30s → 1m → 2m → 4m → 1h (capped) |

### Custom Retry Logic

Pass a callable that receives the attempt number (1-indexed) and returns a `timedelta`:

```python
from datetime import timedelta
from crazyjob import Job

def fibonacci_backoff(attempt: int) -> timedelta:
    a, b = 1, 1
    for _ in range(attempt - 1):
        a, b = b, a + b
    return timedelta(seconds=a * 30)

class MyJob(Job):
    max_attempts = 8
    retry_backoff = fibonacci_backoff
```

### Disabling Retries

```python
class NoRetryJob(Job):
    max_attempts = 1  # fails immediately to dead letters on first error
```

### Manually Retrying from Within perform()

```python
from crazyjob.exceptions import Retry

class SometimesFlaky(Job):
    max_attempts = 5

    def perform(self, resource_id: int):
        resource = fetch_resource(resource_id)

        if resource.is_locked:
            # Retry in exactly 60 seconds, regardless of backoff policy
            raise Retry(in_seconds=60, reason="Resource is locked")

        process(resource)
```

---

## Scheduled (Cron) Jobs

Define recurring jobs using standard cron expressions.

```python
# schedules.py
from crazyjob import Job, schedule

# Every day at 9 AM on weekdays
@schedule(cron="0 9 * * 1-5", name="daily_report")
class DailyReportJob(Job):
    queue = "reports"

    def perform(self):
        generate_and_email_daily_report()

# Every hour
@schedule(cron="0 * * * *", name="hourly_cleanup")
class CleanupJob(Job):
    def perform(self):
        delete_expired_sessions()

# Every 5 minutes
@schedule(cron="*/5 * * * *", name="health_check")
class HealthCheckJob(Job):
    def perform(self):
        ping_external_services()
```

Run the scheduler as a separate process:

```bash
crazyjob scheduler
```

> The scheduler uses `SELECT ... FOR UPDATE SKIP LOCKED` on the schedules table, so running multiple scheduler processes is safe — only one will fire each schedule at the correct time.

---

## Running Workers

### Basic Usage

```bash
# Single queue, 5 concurrent threads
crazyjob worker --queues default --concurrency 5

# Multiple queues (polled in order)
crazyjob worker --queues critical,mailers,default --concurrency 10

# All queues
crazyjob worker --all-queues --concurrency 8
```

### CLI Options

| Option | Default | Description |
|---|---|---|
| `--queues` | `default` | Comma-separated list of queues to consume |
| `--all-queues` | off | Consume all queues found in the database |
| `--concurrency` | `5` | Number of concurrent worker threads |
| `--processes` | `1` | Number of worker processes (for CPU-bound jobs) |
| `--poll-interval` | `1.0` | Seconds between fetch attempts when queue is empty |
| `--shutdown-timeout` | `30` | Seconds to wait for in-flight jobs before force exit |
| `--config` | auto | Path to Python config file |

### Running in Production

**Systemd service:**

```ini
# /etc/systemd/system/crazyjob-worker.service

[Unit]
Description=CrazyJob Worker
After=network.target postgresql.service

[Service]
Type=simple
User=appuser
WorkingDirectory=/var/www/myapp
Environment=FLASK_APP=app.py
Environment=CRAZYJOB_DATABASE_URL=postgresql://user:password@localhost/mydb
ExecStart=/var/www/myapp/venv/bin/crazyjob worker --queues critical,default,mailers --concurrency 10
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable crazyjob-worker
sudo systemctl start crazyjob-worker
```

**Docker:**

```dockerfile
CMD ["crazyjob", "worker", "--all-queues", "--concurrency", "10"]
```

```yaml
# docker-compose.yml
services:
  web:
    build: .
    command: flask run

  worker:
    build: .
    command: crazyjob worker --all-queues --concurrency 10
    environment:
      - CRAZYJOB_DATABASE_URL=postgresql://user:password@db/mydb
    depends_on:
      - db

  scheduler:
    build: .
    command: crazyjob scheduler
    environment:
      - CRAZYJOB_DATABASE_URL=postgresql://user:password@db/mydb
    depends_on:
      - db

  db:
    image: postgres:16
```

---

## Dashboard

### Enabling the Dashboard

```python
app.config.update(
    CRAZYJOB_DASHBOARD_ENABLED=True,
    CRAZYJOB_DASHBOARD_PREFIX="/crazyjob",  # default
)
```

Navigate to `http://localhost:5000/crazyjob`.

### Dashboard Features

| Page | URL | What you see |
|---|---|---|
| **Overview** | `/crazyjob/` | Job counts per status, throughput graph, error rate |
| **Enqueued** | `/crazyjob/queues` | Jobs waiting to run, grouped by queue |
| **Active** | `/crazyjob/active` | Jobs running right now, with elapsed time |
| **Scheduled** | `/crazyjob/scheduled` | Jobs with a future `run_at` |
| **Retrying** | `/crazyjob/retrying` | Failed jobs waiting for next retry attempt |
| **Completed** | `/crazyjob/completed` | History of successful jobs with latency |
| **Failed** | `/crazyjob/failed` | Recent failures with full stacktrace |
| **Dead** | `/crazyjob/dead` | Jobs that exhausted all attempts |
| **Workers** | `/crazyjob/workers` | Active workers, heartbeat status, current job |
| **Schedules** | `/crazyjob/schedules` | Cron job registry, enable/disable, manual trigger |

**Actions available from the dashboard:**
- 🔁 Resurrect a dead job (re-enqueue it)
- 🔁 Bulk resurrect all dead letters
- ❌ Cancel an enqueued job (before it's picked up)
- ⏸️ Pause / resume a queue
- 🗑️ Clear all jobs in a queue
- ▶️ Trigger a schedule manually
- 🔍 Search jobs by class name, argument, or job ID

### Securing the Dashboard

**Basic auth (simplest):**

```python
app.config["CRAZYJOB_DASHBOARD_AUTH"] = ("admin", "s3cr3t-p4ssw0rd")
```

**Custom auth function:**

```python
def my_auth_check(request) -> bool:
    return request.headers.get("X-Internal-Token") == os.environ["INTERNAL_TOKEN"]

app.config["CRAZYJOB_DASHBOARD_AUTH"] = my_auth_check
```

**Flask-Login integration:**

```python
from flask_login import current_user

def require_admin(request) -> bool:
    return current_user.is_authenticated and current_user.is_admin

app.config["CRAZYJOB_DASHBOARD_AUTH"] = require_admin
```

---

## Middleware

### Built-in Middleware

```python
from crazyjob.middleware import (
    LoggingMiddleware,
    SentryMiddleware,
    DatadogMiddleware,
    NewRelicMiddleware,
)

cj = FlaskCrazyJob(app)
cj.use(LoggingMiddleware(level="INFO"))
cj.use(SentryMiddleware())      # reads SENTRY_DSN from env
cj.use(DatadogMiddleware())     # sends metrics to DogStatsD
```

### Writing Custom Middleware

```python
from crazyjob.core.middleware import Middleware
from crazyjob.core.job import JobRecord
import time

class TimingMiddleware(Middleware):

    def before_perform(self, job: JobRecord) -> None:
        job.meta["started_at"] = time.monotonic()

    def after_perform(self, job: JobRecord, result) -> None:
        elapsed = time.monotonic() - job.meta["started_at"]
        print(f"{job.class_path} completed in {elapsed:.2f}s")

    def on_failure(self, job: JobRecord, error: Exception) -> None:
        print(f"{job.class_path} failed: {error}")
        alert_on_call_team(job, error)


# Register globally
cj.use(TimingMiddleware())
```

---

## Configuration Reference

All settings can be provided via `app.config` (Flask), `settings.py` (Django), or environment variables.

| Config Key | Env Variable | Default | Description |
|---|---|---|---|
| `CRAZYJOB_DATABASE_URL` | `CRAZYJOB_DATABASE_URL` | **required** | PostgreSQL DSN |
| `CRAZYJOB_QUEUES` | `CRAZYJOB_QUEUES` | `["default"]` | Default queues for workers |
| `CRAZYJOB_DEFAULT_MAX_ATTEMPTS` | — | `3` | Global default for `max_attempts` |
| `CRAZYJOB_DEFAULT_BACKOFF` | — | `"exponential"` | Global retry strategy |
| `CRAZYJOB_POLL_INTERVAL` | — | `1.0` | Seconds between fetch attempts |
| `CRAZYJOB_JOB_TIMEOUT` | — | `None` | Default job timeout (seconds) |
| `CRAZYJOB_DEAD_LETTER_TTL_DAYS` | — | `30` | Auto-purge dead letters after N days |
| `CRAZYJOB_DASHBOARD_ENABLED` | — | `True` | Enable the web dashboard |
| `CRAZYJOB_DASHBOARD_PREFIX` | — | `"/crazyjob"` | URL prefix for the dashboard |
| `CRAZYJOB_DASHBOARD_AUTH` | — | `None` | Tuple, callable, or `None` |
| `CRAZYJOB_USE_SQLALCHEMY` | — | `False` | Reuse app's SQLAlchemy connection |
| `CRAZYJOB_HEARTBEAT_INTERVAL` | — | `10` | Worker heartbeat frequency (seconds) |
| `CRAZYJOB_DEAD_WORKER_THRESHOLD` | — | `60` | Seconds before worker is considered dead |

---

## Practical Examples

### Sending Emails

```python
# jobs/email_jobs.py
from crazyjob import Job
from myapp.email import send_email
from myapp.models import User

class WelcomeEmailJob(Job):
    queue = "mailers"
    max_attempts = 3
    retry_backoff = "exponential"

    def perform(self, user_id: int):
        user = User.query.get(user_id)
        if not user:
            return  # User deleted — skip silently

        send_email(
            to=user.email,
            subject="Welcome!",
            template="welcome",
            context={"name": user.first_name}
        )


@app.route("/register", methods=["POST"])
def register():
    user = User.create(**request.json)
    db.session.commit()

    WelcomeEmailJob.enqueue(user_id=user.id)
    return jsonify(user.to_dict()), 201
```

---

### Processing File Uploads

```python
# jobs/file_jobs.py
from crazyjob import Job

class ProcessUploadJob(Job):
    queue = "default"
    timeout = timedelta(minutes=15)
    max_attempts = 2

    def perform(self, upload_id: int):
        upload = Upload.query.get(upload_id)
        upload.status = "processing"
        db.session.commit()

        try:
            result = run_image_pipeline(upload.s3_key)
            upload.status = "complete"
            upload.result_url = result.url
        except Exception:
            upload.status = "failed"
            raise  # let CrazyJob handle retry
        finally:
            db.session.commit()


@app.route("/upload", methods=["POST"])
def upload_file():
    file = request.files["file"]
    s3_key = upload_to_s3(file)
    upload = Upload.create(s3_key=s3_key, status="pending")
    db.session.commit()

    ProcessUploadJob.enqueue(upload_id=upload.id)
    return jsonify({"upload_id": upload.id, "status": "pending"}), 202
```

---

### Sending Webhooks with Retry

```python
# jobs/webhook_jobs.py
from crazyjob import Job
from crazyjob.exceptions import Retry
import httpx

class DeliverWebhookJob(Job):
    queue = "webhooks"
    max_attempts = 10
    retry_backoff = "exponential_cap"

    def perform(self, webhook_id: int):
        webhook = Webhook.query.get(webhook_id)
        payload = build_payload(webhook)

        try:
            response = httpx.post(
                webhook.url,
                json=payload,
                timeout=10,
                headers={"X-Webhook-Signature": sign(payload, webhook.secret)}
            )

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                raise Retry(in_seconds=retry_after, reason="Rate limited")

            if response.status_code >= 500:
                raise Retry(reason=f"Server error {response.status_code}")

            response.raise_for_status()

            webhook.last_delivered_at = datetime.utcnow()
            db.session.commit()

        except httpx.TimeoutException:
            raise Retry(reason="Request timed out")
```

---

### Generating Reports

```python
# jobs/report_jobs.py
from crazyjob import Job, schedule
from datetime import timedelta

class GenerateReportJob(Job):
    queue = "reports"
    timeout = timedelta(minutes=30)
    priority = 80

    def perform(self, org_id: int, report_type: str, email_to: str):
        org = Organization.query.get(org_id)
        data = fetch_report_data(org, report_type)
        pdf_path = render_pdf(data, template=report_type)
        s3_url = upload_to_s3(pdf_path)

        send_email(
            to=email_to,
            subject=f"Your {report_type} report is ready",
            template="report_ready",
            context={"download_url": s3_url}
        )


@app.route("/reports/request", methods=["POST"])
def request_report():
    GenerateReportJob.enqueue(
        org_id=current_user.org_id,
        report_type=request.json["type"],
        email_to=current_user.email
    )
    return jsonify({"message": "Report generation started. You'll receive an email shortly."}), 202


# Also runs every Monday at 8 AM
@schedule(cron="0 8 * * 1", name="weekly_report")
class WeeklyReportJob(Job):
    queue = "reports"

    def perform(self):
        for org in Organization.query.filter_by(weekly_report=True).all():
            GenerateReportJob.enqueue(
                org_id=org.id,
                report_type="weekly_summary",
                email_to=org.billing_email
            )
```

---

### Chaining Jobs

Enqueue the next job at the end of `perform()`. Simple and fully traceable in the dashboard.

```python
class Step1Job(Job):
    queue = "pipeline"

    def perform(self, order_id: int):
        result = validate_order(order_id)
        Step2Job.enqueue(order_id=order_id, validation=result)


class Step2Job(Job):
    queue = "pipeline"

    def perform(self, order_id: int, validation: dict):
        charge_customer(order_id, validation)
        Step3Job.enqueue(order_id=order_id)


class Step3Job(Job):
    queue = "pipeline"

    def perform(self, order_id: int):
        send_order_confirmation(order_id)
```

---

### Batch Operations

Fan out a list of IDs into individual jobs:

```python
class SyncAllUsersJob(Job):
    queue = "sync"

    def perform(self):
        user_ids = db.session.query(User.id).all()
        for (user_id,) in user_ids:
            SyncUserJob.enqueue(user_id=user_id)


class SyncUserJob(Job):
    queue = "sync"
    max_attempts = 3

    def perform(self, user_id: int):
        user = User.query.get(user_id)
        sync_to_crm(user)
```

---

## Testing

CrazyJob provides a test mode that runs jobs synchronously in the same process, so you don't need a worker or a PostgreSQL database in your test suite.

```python
# conftest.py
import pytest
from crazyjob.testing import CrazyJobTestMode

@pytest.fixture(autouse=True)
def crazyjob_test_mode():
    with CrazyJobTestMode():
        yield
```

**In test mode:**
- `Job.enqueue()` executes `perform()` immediately and synchronously
- No database writes occur
- Assertions work normally

```python
# tests/test_jobs.py
def test_welcome_email_is_sent(mock_send_email):
    user = UserFactory.create()

    WelcomeEmailJob.enqueue(user_id=user.id)

    mock_send_email.assert_called_once_with(
        to=user.email,
        subject="Welcome!",
        template="welcome",
        context={"name": user.first_name}
    )
```

**Testing that a job was enqueued without running it:**

```python
from crazyjob.testing import assert_enqueued, assert_not_enqueued

def test_registration_enqueues_welcome_email(client):
    with CrazyJobTestMode(execute=False):
        client.post("/register", json={"email": "test@example.com"})

        assert_enqueued(WelcomeEmailJob, email="test@example.com")
        assert_not_enqueued(AdminAlertJob)
```

---

## Error Handling & Monitoring

### Accessing Error Details

Failed and dead jobs store the full Python traceback in the database. You can inspect them from the **Failed** and **Dead** pages in the dashboard, or query directly:

```sql
SELECT class_path, error, attempts FROM cj_jobs WHERE status = 'failed';
```

### Integrating with Sentry

```python
import sentry_sdk
from crazyjob.middleware import SentryMiddleware

sentry_sdk.init(dsn=os.environ["SENTRY_DSN"])
cj.use(SentryMiddleware())
```

CrazyJob attaches job metadata (job ID, class, queue, attempt number) to each Sentry event automatically.

### Custom Failure Handler

```python
from crazyjob.core.middleware import Middleware

class AlertMiddleware(Middleware):
    def on_failure(self, job, error):
        if job.attempts >= job.max_attempts:
            notify_slack(
                f"💀 Job {job.class_path} has died after {job.attempts} attempts.\n"
                f"Error: {error}\n"
                f"Dashboard: https://myapp.com/crazyjob/dead"
            )
```

---

## FAQ

**Q: Can I use CrazyJob without a web framework, in a plain Python script?**

Yes. Use the core directly without any framework integration:

```python
from crazyjob.backends.postgresql import PostgreSQLDriver
from crazyjob.core.client import Client

backend = PostgreSQLDriver(database_url="postgresql://...")
client = Client(backend=backend)

client.enqueue("myapp.jobs.MyJob", kwargs={"user_id": 1})
```

---

**Q: What happens to jobs if the worker crashes mid-execution?**

If a worker process crashes (OOM kill, `kill -9`, power loss), its heartbeat stops updating. After 60 seconds (configurable), another worker detects the stale heartbeat and re-enqueues any jobs that were `active` on the dead worker. They will be retried normally.

---

**Q: Can I run multiple workers?**

Yes. Start as many worker processes as you need. `SELECT ... FOR UPDATE SKIP LOCKED` guarantees each job is picked up by exactly one worker, even with dozens of workers running in parallel across multiple machines.

---

**Q: Does CrazyJob support async jobs (async def perform)?**

Not in the current version. `perform()` must be synchronous. For async frameworks like FastAPI, the worker runs synchronous jobs in a thread pool. Native `async def perform()` support is planned for a future release.

---

**Q: How do I clear old completed jobs to save disk space?**

From the dashboard: go to **Completed → Clear All**.

Via CLI:

```bash
crazyjob purge --status completed --older-than 30d
crazyjob purge --status dead --older-than 7d
```

Via Python:

```python
from crazyjob.core.client import Client
client.purge(status="completed", older_than_days=30)
```

---

**Q: Is CrazyJob safe to use with PgBouncer?**

Yes, with transaction-mode pooling. CrazyJob uses short-lived transactions for job fetching. Avoid session-mode pooling as it may interfere with `SKIP LOCKED`.

---

*For architecture details, backend internals, and integration guides for framework authors, see [ARCHITECTURE.md](https://github.com/juniortada/crazy_job/blob/main/ARCHITECTURE.md).*
