"""Schema management for CrazyJob PostgreSQL backend."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def apply_schema(driver: object) -> None:
    """Apply all SQL migrations to create cj_* tables.

    Reads migration files from the migrations/ directory and executes them
    in order. Uses the driver's connection pool to get a cursor.
    """
    migration_file = MIGRATIONS_DIR / "001_initial.sql"
    sql = migration_file.read_text()

    with driver._conn() as conn, conn.cursor() as cur:  # type: ignore[attr-defined]
        cur.execute(sql)

    logger.info("CrazyJob schema applied successfully")
