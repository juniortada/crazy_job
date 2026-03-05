"""Flask app context utilities for CrazyJob."""
from __future__ import annotations

from typing import Any, Callable


def with_app_context(app: Any, func: Callable) -> Callable:
    """Wrap a callable to run inside a Flask app context."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with app.app_context():
            return func(*args, **kwargs)

    return wrapper
