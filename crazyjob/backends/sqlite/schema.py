"""Schema management for CrazyJob SQLite backend."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def apply_schema(driver: object) -> None:
    """Apply all SQL migrations to create cj_* tables.

    Reads migration files from the migrations/ directory and executes them.
    Uses the driver's connection directly (SQLite has no connection pool).
    """
    migration_file = MIGRATIONS_DIR / "001_initial.sql"
    sql = migration_file.read_text()

    with driver._cursor() as cur:  # type: ignore[attr-defined]
        cur.executescript(sql)

    logger.info("CrazyJob SQLite schema applied successfully")
