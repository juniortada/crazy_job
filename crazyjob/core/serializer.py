"""JSON serialization with support for datetime and UUID types."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


class Serializer:
    """Serialize and deserialize job arguments to/from JSON.

    Supports datetime (ISO 8601) and UUID beyond standard JSON types.
    Raises TypeError immediately for unsupported types.
    """

    @staticmethod
    def dumps(data: Any) -> str:
        """Serialize data to a JSON string."""
        return json.dumps(data, default=Serializer._encode)

    @staticmethod
    def loads(raw: str) -> Any:
        """Deserialize a JSON string back to Python objects."""
        return json.loads(raw, object_hook=Serializer._decode)

    @staticmethod
    def _encode(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return {"__type__": "datetime", "value": obj.isoformat()}
        if isinstance(obj, UUID):
            return {"__type__": "uuid", "value": str(obj)}
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    @staticmethod
    def _decode(obj: dict) -> Any:
        if "__type__" not in obj:
            return obj
        match obj["__type__"]:
            case "datetime":
                return datetime.fromisoformat(obj["value"])
            case "uuid":
                return UUID(obj["value"])
            case _:
                return obj
