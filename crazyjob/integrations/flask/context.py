"""Flask app context utilities for CrazyJob."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def with_app_context(app: Any, func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a callable to run inside a Flask app context."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with app.app_context():
            return func(*args, **kwargs)

    return wrapper
