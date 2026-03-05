"""Middleware pipeline for wrapping job execution."""
from __future__ import annotations

from abc import ABC
from typing import Any, Callable

from crazyjob.core.job import JobRecord


class Middleware(ABC):
    """Base class for job execution middleware.

    Override any of the hook methods to add behavior before, after, or on
    failure of job execution.
    """

    def before_perform(self, job: JobRecord) -> None:
        """Called before perform() runs."""

    def after_perform(self, job: JobRecord, result: Any) -> None:
        """Called after perform() succeeds."""

    def on_failure(self, job: JobRecord, error: Exception) -> None:
        """Called when perform() raises an exception."""


class MiddlewarePipeline:
    """Runs a chain of middleware around job execution."""

    def __init__(self, middlewares: list[Middleware] | None = None) -> None:
        self._middlewares: list[Middleware] = middlewares or []

    def add(self, middleware: Middleware) -> None:
        """Add a middleware to the pipeline."""
        self._middlewares.append(middleware)

    def run(self, job: JobRecord, perform_fn: Callable) -> Any:
        """Execute perform_fn wrapped by all registered middleware."""
        for mw in self._middlewares:
            mw.before_perform(job)
        try:
            result = perform_fn()
            for mw in self._middlewares:
                mw.after_perform(job, result)
            return result
        except Exception as e:
            for mw in self._middlewares:
                mw.on_failure(job, e)
            raise
