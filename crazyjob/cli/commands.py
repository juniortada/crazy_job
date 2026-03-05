"""CrazyJob CLI commands — worker, scheduler, migrate, purge."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from crazyjob.backends.base import BackendDriver

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    """CrazyJob — background job processing powered by PostgreSQL or SQLite."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@cli.command()
@click.option("--queues", default="default", help="Comma-separated list of queues")
@click.option("--all-queues", is_flag=True, help="Consume all queues")
@click.option("--concurrency", default=5, type=int, help="Number of worker threads")
@click.option("--processes", default=1, type=int, help="Number of worker processes")
@click.option("--poll-interval", default=1.0, type=float, help="Poll interval in seconds")
@click.option("--shutdown-timeout", default=30, type=int, help="Shutdown timeout in seconds")
def worker(
    queues: str,
    all_queues: bool,
    concurrency: int,
    processes: int,
    poll_interval: float,
    shutdown_timeout: int,
) -> None:
    """Start a CrazyJob worker."""
    from crazyjob.core.worker import Worker

    database_url = _get_database_url()
    backend = _create_backend(database_url)

    queue_list: list[str]
    if all_queues:
        with backend._cursor() as cur:  # type: ignore[attr-defined]
            cur.execute("SELECT DISTINCT queue FROM cj_jobs;")
            queue_list = [row["queue"] for row in cur.fetchall()]
        if not queue_list:
            queue_list = ["default"]
    else:
        queue_list = [q.strip() for q in queues.split(",")]

    w = Worker(
        backend=backend,
        queues=queue_list,
        concurrency=concurrency,
        poll_interval=poll_interval,
        shutdown_timeout=shutdown_timeout,
    )
    w.run()


@cli.command()
def scheduler() -> None:
    """Start the CrazyJob cron scheduler."""
    from crazyjob.core.scheduler import Scheduler

    database_url = _get_database_url()
    backend = _create_backend(database_url)

    s = Scheduler(backend=backend)
    s.run()


@cli.command()
@click.option(
    "--database-url",
    default=None,
    help="Database connection string (or set CRAZYJOB_DATABASE_URL)",
)
def migrate(database_url: str | None) -> None:
    """Create CrazyJob database tables (cj_*)."""
    url = database_url or _get_database_url()
    backend = _create_backend(url)

    if url.startswith("sqlite"):
        from crazyjob.backends.sqlite.schema import apply_schema
    else:
        from crazyjob.backends.postgresql.schema import apply_schema

    apply_schema(backend)
    click.echo("CrazyJob schema applied successfully.")
    backend.close()


@cli.command()
@click.option("--status", required=True, help="Job status to purge (completed, dead, failed)")
@click.option("--older-than", required=True, help="Age threshold (e.g. 30d, 7d)")
def purge(status: str, older_than: str) -> None:
    """Purge old jobs by status and age."""
    database_url = _get_database_url()
    backend = _create_backend(database_url)

    if older_than.endswith("d"):
        days = int(older_than[:-1])
    else:
        raise click.BadParameter("Use format like '30d' for days")

    is_sqlite = database_url.startswith("sqlite")

    if status == "dead":
        if is_sqlite:
            sql = "DELETE FROM cj_dead_letters WHERE killed_at < datetime('now', ? || ' days');"
            params: tuple[object, ...] = (f"-{days}",)
        else:
            sql = "DELETE FROM cj_dead_letters WHERE killed_at < NOW() - INTERVAL '%s days';"
            params = (days,)
    else:
        if is_sqlite:
            sql = (
                "DELETE FROM cj_jobs "
                "WHERE status = ? AND updated_at < datetime('now', ? || ' days');"
            )
            params = (status, f"-{days}")
        else:
            sql = (
                "DELETE FROM cj_jobs "
                "WHERE status = %s AND updated_at < NOW() - INTERVAL '%s days';"
            )
            params = (status, days)

    with backend._cursor() as cur:  # type: ignore[attr-defined]
        cur.execute(sql, params)

    click.echo(f"Purged {status} jobs older than {older_than}.")
    backend.close()


def _get_database_url() -> str:
    """Get the database URL from environment."""
    url = os.environ.get("CRAZYJOB_DATABASE_URL")
    if not url:
        raise click.ClickException(
            "CRAZYJOB_DATABASE_URL environment variable is not set. "
            "Set it or pass --database-url."
        )
    return url


def _create_backend(database_url: str) -> BackendDriver:
    """Create the appropriate backend driver based on URL scheme."""
    if database_url.startswith("sqlite"):
        from crazyjob.backends.sqlite.driver import SQLiteDriver

        path = database_url.replace("sqlite:///", "").replace("sqlite://", "")
        return SQLiteDriver(database_path=path or ":memory:")

    from crazyjob.backends.postgresql.driver import PostgreSQLDriver

    return PostgreSQLDriver(dsn=database_url)
