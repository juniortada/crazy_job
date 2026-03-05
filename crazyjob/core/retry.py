"""Retry backoff policies for CrazyJob."""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Callable


class BackoffPolicy(ABC):
    """Abstract base class for retry backoff strategies."""

    @abstractmethod
    def delay_for(self, attempt: int) -> timedelta:
        """Calculate the delay before the next retry attempt."""
        ...


class LinearBackoff(BackoffPolicy):
    """Linear backoff: delay = attempt * base_seconds."""

    def __init__(self, base_seconds: int = 30, jitter: bool = True) -> None:
        self.base_seconds = base_seconds
        self.jitter = jitter

    def delay_for(self, attempt: int) -> timedelta:
        seconds = attempt * self.base_seconds
        if self.jitter:
            seconds *= random.uniform(0.9, 1.1)
        return timedelta(seconds=seconds)


class ExponentialBackoff(BackoffPolicy):
    """Exponential backoff: delay = (2 ** attempt) * base_seconds."""

    def __init__(self, base_seconds: int = 15, jitter: bool = True) -> None:
        self.base_seconds = base_seconds
        self.jitter = jitter

    def delay_for(self, attempt: int) -> timedelta:
        seconds = (2**attempt) * self.base_seconds
        if self.jitter:
            seconds *= random.uniform(0.9, 1.1)
        return timedelta(seconds=seconds)


class ExponentialCapBackoff(BackoffPolicy):
    """Exponential backoff with a maximum cap."""

    def __init__(
        self, base_seconds: int = 15, cap_seconds: int = 3600, jitter: bool = True
    ) -> None:
        self.base_seconds = base_seconds
        self.cap_seconds = cap_seconds
        self.jitter = jitter

    def delay_for(self, attempt: int) -> timedelta:
        seconds = min((2**attempt) * self.base_seconds, self.cap_seconds)
        if self.jitter:
            seconds *= random.uniform(0.9, 1.1)
        return timedelta(seconds=seconds)


class _CallablePolicy(BackoffPolicy):
    """Wraps a raw callable in a BackoffPolicy interface."""

    def __init__(self, fn: Callable[[int], timedelta]) -> None:
        self._fn = fn

    def delay_for(self, attempt: int) -> timedelta:
        return self._fn(attempt)


def get_backoff_policy(name: str | BackoffPolicy | Callable) -> BackoffPolicy:
    """Resolve a backoff policy from a string name, instance, or callable."""
    if isinstance(name, BackoffPolicy):
        return name
    if callable(name) and not isinstance(name, str):
        return _CallablePolicy(name)
    policies: dict[str, type[BackoffPolicy]] = {
        "linear": LinearBackoff,
        "exponential": ExponentialBackoff,
        "exponential_cap": ExponentialCapBackoff,
    }
    if name not in policies:
        raise ValueError(f"Unknown backoff policy: {name!r}. Choose from {list(policies)}")
    return policies[name]()
