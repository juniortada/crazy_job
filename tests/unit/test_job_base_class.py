"""Unit tests for the base Job class."""

from __future__ import annotations

import pytest

from crazyjob.core.job import Job, JobRecord


@pytest.mark.unit
class TestJobRecord:
    def test_default_values(self) -> None:
        record = JobRecord(class_path="app.jobs.MyJob", args=[], kwargs={})
        assert record.queue == "default"
        assert record.priority == 50
        assert record.max_attempts == 3
        assert record.status == "enqueued"
        assert record.attempts == 0
        assert record.run_at is None
        assert record.worker_id is None
        assert record.id is not None

    def test_custom_values(self) -> None:
        record = JobRecord(
            class_path="app.jobs.MyJob",
            args=[1, 2],
            kwargs={"key": "value"},
            queue="critical",
            priority=10,
            max_attempts=5,
        )
        assert record.queue == "critical"
        assert record.priority == 10
        assert record.max_attempts == 5
        assert record.args == [1, 2]
        assert record.kwargs == {"key": "value"}

    def test_each_record_gets_unique_id(self) -> None:
        r1 = JobRecord(class_path="a.B", args=[], kwargs={})
        r2 = JobRecord(class_path="a.B", args=[], kwargs={})
        assert r1.id != r2.id


@pytest.mark.unit
class TestJobBaseClass:
    def test_perform_raises_not_implemented(self) -> None:
        job = Job()
        with pytest.raises(NotImplementedError):
            job.perform()

    def test_class_path(self) -> None:
        class MyJob(Job):
            pass

        path = MyJob._class_path()
        assert path.endswith("MyJob")
        assert "test_job_base_class" in path

    def test_default_class_config(self) -> None:
        assert Job.queue == "default"
        assert Job.max_attempts == 3
        assert Job.retry_backoff == "exponential"
        assert Job.retry_jitter is True
        assert Job.timeout is None
        assert Job.priority == 50
