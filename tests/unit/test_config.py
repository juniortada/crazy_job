"""Unit tests for CrazyJobConfig."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from crazyjob.config import CrazyJobConfig


@pytest.mark.unit
class TestCrazyJobConfig:
    def test_default_values(self) -> None:
        config = CrazyJobConfig(database_url="postgresql://localhost/test")
        assert config.queues == ["default"]
        assert config.default_max_attempts == 3
        assert config.default_backoff == "exponential"
        assert config.poll_interval == 1.0
        assert config.job_timeout is None
        assert config.dead_letter_ttl_days == 30
        assert config.dashboard_enabled is True
        assert config.dashboard_prefix == "/crazyjob"
        assert config.dashboard_auth is None
        assert config.use_sqlalchemy is False
        assert config.heartbeat_interval == 10
        assert config.dead_worker_threshold == 60

    def test_from_flask(self) -> None:
        app = MagicMock()
        app.config = {
            "CRAZYJOB_DATABASE_URL": "postgresql://localhost/mydb",
            "CRAZYJOB_QUEUES": ["critical", "default"],
            "CRAZYJOB_DEFAULT_MAX_ATTEMPTS": 5,
            "CRAZYJOB_POLL_INTERVAL": 0.5,
        }
        config = CrazyJobConfig.from_flask(app)
        assert config.database_url == "postgresql://localhost/mydb"
        assert config.queues == ["critical", "default"]
        assert config.default_max_attempts == 5
        assert config.poll_interval == 0.5

    def test_from_flask_requires_database_url(self) -> None:
        app = MagicMock()
        app.config = {}
        with pytest.raises(KeyError):
            CrazyJobConfig.from_flask(app)

    def test_from_dict(self) -> None:
        config = CrazyJobConfig.from_dict(
            {"database_url": "postgresql://localhost/test", "poll_interval": 2.0}
        )
        assert config.database_url == "postgresql://localhost/test"
        assert config.poll_interval == 2.0
