"""Unit tests for the JSON serializer."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from crazyjob.core.serializer import Serializer


@pytest.mark.unit
class TestSerializer:
    def test_roundtrip_primitives(self) -> None:
        data = {"name": "test", "count": 42, "active": True, "score": 3.14}
        assert Serializer.loads(Serializer.dumps(data)) == data

    def test_roundtrip_datetime(self) -> None:
        dt = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone.utc)
        result = Serializer.loads(Serializer.dumps({"ts": dt}))
        assert result["ts"] == dt

    def test_roundtrip_uuid(self) -> None:
        uid = UUID("12345678-1234-5678-1234-567812345678")
        result = Serializer.loads(Serializer.dumps({"id": uid}))
        assert result["id"] == uid

    def test_roundtrip_nested_structures(self) -> None:
        data = {"list": [1, 2, 3], "nested": {"key": "value"}}
        assert Serializer.loads(Serializer.dumps(data)) == data

    def test_roundtrip_none(self) -> None:
        data = {"value": None}
        assert Serializer.loads(Serializer.dumps(data)) == data

    def test_rejects_non_serializable_objects(self) -> None:
        with pytest.raises(TypeError):
            Serializer.dumps({"obj": object()})

    def test_rejects_set(self) -> None:
        with pytest.raises(TypeError):
            Serializer.dumps({"items": {1, 2, 3}})
