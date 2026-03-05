"""Unit tests for the middleware pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from crazyjob.core.middleware import MiddlewarePipeline


@pytest.mark.unit
def test_pipeline_calls_before_and_after_in_order() -> None:
    m1, m2 = MagicMock(), MagicMock()
    pipeline = MiddlewarePipeline([m1, m2])
    job = MagicMock()

    pipeline.run(job, lambda: None)

    assert m1.before_perform.call_args == call(job)
    assert m2.before_perform.call_args == call(job)
    assert m1.after_perform.called
    assert m2.after_perform.called


@pytest.mark.unit
def test_pipeline_calls_on_failure_when_perform_raises() -> None:
    m = MagicMock()
    pipeline = MiddlewarePipeline([m])
    job = MagicMock()
    error = ValueError("boom")

    with pytest.raises(ValueError):
        pipeline.run(job, lambda: (_ for _ in ()).throw(error))

    m.on_failure.assert_called_once_with(job, error)
    m.after_perform.assert_not_called()


@pytest.mark.unit
def test_pipeline_does_not_call_after_perform_on_failure() -> None:
    m = MagicMock()
    pipeline = MiddlewarePipeline([m])
    job = MagicMock()

    with pytest.raises(RuntimeError):
        pipeline.run(job, lambda: (_ for _ in ()).throw(RuntimeError("fail")))

    m.after_perform.assert_not_called()


@pytest.mark.unit
def test_empty_pipeline_runs_perform() -> None:
    pipeline = MiddlewarePipeline()
    result = pipeline.run(MagicMock(), lambda: 42)
    assert result == 42


@pytest.mark.unit
def test_add_middleware() -> None:
    pipeline = MiddlewarePipeline()
    m = MagicMock()
    pipeline.add(m)
    job = MagicMock()

    pipeline.run(job, lambda: None)

    m.before_perform.assert_called_once_with(job)
