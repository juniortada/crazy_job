"""CrazyJob CLI commands — worker, scheduler, migrate, purge."""
from __future__ import annotations

import logging
import os

import click

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    """CrazyJob — background job processing powered by PostgreSQL."""
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
    from crazyjob.backends.postgresql.driver import PostgreSQLDriver
    from crazyjob.core.worker import Worker

    database_url = _get_database_url()
    backend = PostgreSQLDriver(dsn=database_url)

    queue_list: list[str]
    if all_queues:
        # Fetch all distinct queues from the database
        with backend._cursor() as cur:
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
    from crazyjob.backends.postgresql.driver import PostgreSQLDriver
    from crazyjob.core.scheduler import Scheduler

    database_url = _get_database_url()
    backend = PostgreSQLDriver(dsn=database_url)

    s = Scheduler(backend=backend)
    s.run()


@cli.command()
@click.option(
    "--database-url",
    default=None,
    help="PostgreSQL connection string (or set CRAZYJOB_DATABASE_URL)",
)
def migrate(database_url: str | None) -> None:
    """Create CrazyJob database tables (cj_*)."""
    from crazyjob.backends.postgresql.driver import PostgreSQLDriver
    from crazyjob.backends.postgresql.schema import apply_schema

    url = database_url or _get_database_url()
    backend = PostgreSQLDriver(dsn=url)
    apply_schema(backend)
    click.echo("CrazyJob schema applied successfully.")
    backend.close()


@cli.command()
@click.option("--status", required=True, help="Job status to purge (completed, dead, failed)")
@click.option("--older-than", required=True, help="Age threshold (e.g. 30d, 7d)")
def purge(status: str, older_than: str) -> None:
    """Purge old jobs by status and age."""
    from crazyjob.backends.postgresql.driver import PostgreSQLDriver

    database_url = _get_database_url()
    backend = PostgreSQLDriver(dsn=database_url)

    # Parse older_than (e.g. "30d" → 30 days)
    if older_than.endswith("d"):
        days = int(older_than[:-1])
    else:
        raise click.BadParameter("Use format like '30d' for days")

    if status == "dead":
        sql = """
            DELETE FROM cj_dead_letters
            WHERE killed_at < NOW() - INTERVAL '%s days';
        """
    else:
        sql = """
            DELETE FROM cj_jobs
            WHERE status = %s AND updated_at < NOW() - INTERVAL '%s days';
        """

    with backend._cursor() as cur:
        if status == "dead":
            cur.execute(sql, (days,))
        else:
            cur.execute(sql, (status, days))

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
