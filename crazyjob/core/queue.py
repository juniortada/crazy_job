"""Queue abstraction for CrazyJob."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Queue:
    """Represents a named job queue."""

    name: str

    def __str__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.name == other
        if isinstance(other, Queue):
            return self.name == other.name
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.name)
