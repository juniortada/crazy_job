"""Unit tests for the schedule decorator."""

from __future__ import annotations

import pytest

from crazyjob import Job, schedule


@pytest.mark.unit
class TestScheduleDecorator:
    def test_attaches_cron_metadata(self) -> None:
        @schedule(cron="0 9 * * 1-5", name="daily_report")
        class DailyReportJob(Job):
            def perform(self) -> None:
                pass

        assert DailyReportJob._crazyjob_schedule_cron == "0 9 * * 1-5"
        assert DailyReportJob._crazyjob_schedule_name == "daily_report"

    def test_class_is_still_a_job(self) -> None:
        @schedule(cron="* * * * *", name="every_minute")
        class FrequentJob(Job):
            def perform(self) -> None:
                pass

        assert issubclass(FrequentJob, Job)
