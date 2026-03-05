"""CrazyJob configuration dataclass."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CrazyJobConfig:
    """Central configuration for CrazyJob."""

    database_url: str
    queues: list[str] = field(default_factory=lambda: ["default"])
    default_max_attempts: int = 3
    default_backoff: str = "exponential"
    poll_interval: float = 1.0
    job_timeout: int | None = None
    dead_letter_ttl_days: int = 30
    dashboard_enabled: bool = True
    dashboard_prefix: str = "/crazyjob"
    dashboard_auth: tuple[str, str] | Callable | None = None
    use_sqlalchemy: bool = False
    heartbeat_interval: int = 10
    dead_worker_threshold: int = 60

    @classmethod
    def from_flask(cls, app: Any) -> CrazyJobConfig:
        """Build config from a Flask app's config dict."""
        c = app.config
        return cls(
            database_url=c["CRAZYJOB_DATABASE_URL"],
            queues=c.get("CRAZYJOB_QUEUES", ["default"]),
            default_max_attempts=c.get("CRAZYJOB_DEFAULT_MAX_ATTEMPTS", 3),
            default_backoff=c.get("CRAZYJOB_DEFAULT_BACKOFF", "exponential"),
            poll_interval=c.get("CRAZYJOB_POLL_INTERVAL", 1.0),
            job_timeout=c.get("CRAZYJOB_JOB_TIMEOUT"),
            dead_letter_ttl_days=c.get("CRAZYJOB_DEAD_LETTER_TTL_DAYS", 30),
            dashboard_enabled=c.get("CRAZYJOB_DASHBOARD_ENABLED", True),
            dashboard_prefix=c.get("CRAZYJOB_DASHBOARD_PREFIX", "/crazyjob"),
            dashboard_auth=c.get("CRAZYJOB_DASHBOARD_AUTH"),
            use_sqlalchemy=c.get("CRAZYJOB_USE_SQLALCHEMY", False),
            heartbeat_interval=c.get("CRAZYJOB_HEARTBEAT_INTERVAL", 10),
            dead_worker_threshold=c.get("CRAZYJOB_DEAD_WORKER_THRESHOLD", 60),
        )

    @classmethod
    def from_dict(cls, d: dict) -> CrazyJobConfig:
        """Build config from a plain dictionary."""
        return cls(**{k.lower(): v for k, v in d.items()})
