"""Unit tests for FastAPI integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from crazyjob.config import CrazyJobConfig


class TestFastAPICrazyJob:
    def test_get_config_from_settings(self):
        from crazyjob.integrations.fastapi import FastAPICrazyJob

        cj = FastAPICrazyJob(settings={"database_url": "sqlite:///:memory:"})
        config = cj.get_config()
        assert isinstance(config, CrazyJobConfig)
        assert config.database_url == "sqlite:///:memory:"

    def test_get_backend_sqlite(self):
        from crazyjob.backends.sqlite.driver import SQLiteDriver
        from crazyjob.integrations.fastapi import FastAPICrazyJob

        cj = FastAPICrazyJob(settings={"database_url": "sqlite:///:memory:"})
        backend = cj.get_backend()
        assert isinstance(backend, SQLiteDriver)
        backend.close()

    def test_get_backend_postgresql(self):
        from crazyjob.integrations.fastapi import _create_backend

        with patch("crazyjob.backends.postgresql.driver.PostgreSQLDriver") as mock_pg:
            _create_backend("postgresql://user:pass@localhost/db")
            mock_pg.assert_called_once_with(dsn="postgresql://user:pass@localhost/db")

    def test_wrap_job_context_is_passthrough(self):
        from crazyjob.integrations.fastapi import FastAPICrazyJob

        cj = FastAPICrazyJob(settings={"database_url": "sqlite:///:memory:"})

        def my_func():
            return 42

        wrapped = cj.wrap_job_context(my_func)
        assert wrapped is my_func

    def test_use_registers_middleware(self):
        from crazyjob.core.middleware import Middleware
        from crazyjob.integrations.fastapi import FastAPICrazyJob

        class DummyMiddleware(Middleware):
            pass

        cj = FastAPICrazyJob(settings={"database_url": "sqlite:///:memory:"})
        mw = DummyMiddleware()
        cj.use(mw)
        assert mw in cj.pipeline._middlewares

    def test_backend_property_raises_before_init(self):
        from crazyjob.integrations.fastapi import FastAPICrazyJob

        cj = FastAPICrazyJob(settings={"database_url": "sqlite:///:memory:"})
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = cj.backend
