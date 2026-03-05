"""Unit tests for retry backoff policies."""

from __future__ import annotations

from datetime import timedelta

import pytest

from crazyjob.core.retry import (
    ExponentialBackoff,
    ExponentialCapBackoff,
    LinearBackoff,
    get_backoff_policy,
)


@pytest.mark.unit
class TestLinearBackoff:
    def test_delay_increases_linearly(self) -> None:
        policy = LinearBackoff(base_seconds=30, jitter=False)
        delays = [policy.delay_for(i).total_seconds() for i in range(1, 6)]
        assert delays == [30, 60, 90, 120, 150]

    def test_jitter_stays_within_bounds(self) -> None:
        policy = LinearBackoff(base_seconds=30, jitter=True)
        for attempt in range(1, 6):
            delay = policy.delay_for(attempt).total_seconds()
            base = attempt * 30
            assert base * 0.9 <= delay <= base * 1.1


@pytest.mark.unit
class TestExponentialBackoff:
    def test_first_attempt_delay(self) -> None:
        policy = ExponentialBackoff(base_seconds=15, jitter=False)
        assert policy.delay_for(attempt=1) == timedelta(seconds=30)

    def test_second_attempt_delay(self) -> None:
        policy = ExponentialBackoff(base_seconds=15, jitter=False)
        assert policy.delay_for(attempt=2) == timedelta(seconds=60)

    def test_delay_doubles_each_attempt(self) -> None:
        policy = ExponentialBackoff(base_seconds=15, jitter=False)
        delays = [policy.delay_for(i).total_seconds() for i in range(1, 6)]
        assert delays == [30, 60, 120, 240, 480]

    def test_jitter_stays_within_bounds(self) -> None:
        policy = ExponentialBackoff(base_seconds=15, jitter=True)
        for attempt in range(1, 6):
            delay = policy.delay_for(attempt).total_seconds()
            base = 15 * (2**attempt)
            assert base * 0.9 <= delay <= base * 1.1


@pytest.mark.unit
class TestExponentialCapBackoff:
    def test_capped_at_max(self) -> None:
        policy = ExponentialCapBackoff(base_seconds=15, cap_seconds=100, jitter=False)
        delay = policy.delay_for(attempt=10).total_seconds()
        assert delay == 100

    def test_under_cap_behaves_like_exponential(self) -> None:
        policy = ExponentialCapBackoff(base_seconds=15, cap_seconds=3600, jitter=False)
        assert policy.delay_for(1) == timedelta(seconds=30)
        assert policy.delay_for(2) == timedelta(seconds=60)


@pytest.mark.unit
class TestGetBackoffPolicy:
    def test_resolves_string_names(self) -> None:
        assert isinstance(get_backoff_policy("linear"), LinearBackoff)
        assert isinstance(get_backoff_policy("exponential"), ExponentialBackoff)
        assert isinstance(get_backoff_policy("exponential_cap"), ExponentialCapBackoff)

    def test_passes_through_instance(self) -> None:
        policy = LinearBackoff()
        assert get_backoff_policy(policy) is policy

    def test_wraps_callable(self) -> None:
        def fn(attempt):
            return timedelta(seconds=attempt * 10)

        policy = get_backoff_policy(fn)
        assert policy.delay_for(3) == timedelta(seconds=30)

    def test_raises_for_unknown_name(self) -> None:
        with pytest.raises(ValueError, match="Unknown backoff policy"):
            get_backoff_policy("unknown")
