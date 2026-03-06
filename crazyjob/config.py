"""CrazyJob configuration dataclass.

SRP: This class holds configuration data only. Framework-specific factories
(e.g. config_from_flask) live in crazyjob/integrations/<framework>.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


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
    dashboard_auth: tuple[str, str] | Callable[..., bool] | None = None
    use_sqlalchemy: bool = False
    heartbeat_interval: int = 10
    dead_worker_threshold: int = 60

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> CrazyJobConfig:
        """Build config from a plain dictionary."""
        return cls(**{k.lower(): v for k, v in d.items()})  # type: ignore[arg-type]
