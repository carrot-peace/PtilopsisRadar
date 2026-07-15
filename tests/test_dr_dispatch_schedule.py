# coding=utf-8
"""Schedule-aware DR live-delivery deduplication tests."""

from types import SimpleNamespace
import unittest

from trendradar.dr.dispatch_schedule import (
    DR_DISPATCH_SCHEDULE_ACTION,
    record_scheduled_live_dispatch,
    should_run_scheduled_live_dispatch,
)


class TestDRDispatchSchedule(unittest.TestCase):
    class FakeScheduler:
        def __init__(self, already=False):
            self.already = already
            self.checked = []
            self.recorded = []

        def already_executed(self, period_key, action, date_str):
            self.checked.append((period_key, action, date_str))
            return self.already

        def record_execution(self, period_key, action, date_str):
            self.recorded.append((period_key, action, date_str))

    def test_once_period_requires_a_fresh_result_and_no_prior_delivery(self):
        schedule = SimpleNamespace(once_analyze=True, period_key="daily_evening")
        scheduler = self.FakeScheduler()
        self.assertFalse(should_run_scheduled_live_dispatch(
            schedule=schedule,
            scheduler=scheduler,
            date_str="2026-06-18",
            has_analysis_result=False,
        ))
        self.assertTrue(should_run_scheduled_live_dispatch(
            schedule=schedule,
            scheduler=scheduler,
            date_str="2026-06-18",
            has_analysis_result=True,
        ))
        scheduler.already = True
        self.assertFalse(should_run_scheduled_live_dispatch(
            schedule=schedule,
            scheduler=scheduler,
            date_str="2026-06-18",
            has_analysis_result=True,
        ))

    def test_accepted_once_delivery_is_recorded_with_a_separate_action(self):
        schedule = SimpleNamespace(once_analyze=True, period_key="daily_evening")
        scheduler = self.FakeScheduler()
        record_scheduled_live_dispatch(
            schedule=schedule,
            scheduler=scheduler,
            date_str="2026-06-18",
        )
        self.assertEqual(
            scheduler.recorded,
            [("daily_evening", DR_DISPATCH_SCHEDULE_ACTION, "2026-06-18")],
        )

    def test_non_once_schedule_remains_eligible(self):
        schedule = SimpleNamespace(once_analyze=False, period_key=None)
        scheduler = self.FakeScheduler(already=True)
        self.assertTrue(should_run_scheduled_live_dispatch(
            schedule=schedule,
            scheduler=scheduler,
            date_str="2026-06-18",
            has_analysis_result=False,
        ))
        self.assertEqual(scheduler.checked, [])


if __name__ == "__main__":
    unittest.main()
