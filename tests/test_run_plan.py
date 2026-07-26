# coding=utf-8
"""Contracts for the immutable per-run schedule snapshot."""

import unittest
from dataclasses import FrozenInstanceError

from trendradar.application.run_plan import RunPlanBuilder
from trendradar.core.scheduler import ResolvedSchedule


class TestRunPlanBuilder(unittest.TestCase):
    def test_schedule_values_are_copied_into_an_immutable_snapshot(self):
        schedule = ResolvedSchedule(
            period_key="morning",
            period_name="Morning",
            day_plan="weekday",
            collect=True,
            analyze=False,
            report_mode="daily",
            ai_mode="current",
            once_analyze=True,
            frequency_file="scheduled.txt",
            filter_method="ai",
            interests_file="scheduled-interests.txt",
        )
        config = {"FILTER": {"METHOD": "keyword"}}

        plan = RunPlanBuilder.build(schedule, config)

        self.assertEqual(plan.period_key, "morning")
        self.assertEqual(plan.period_name, "Morning")
        self.assertEqual(plan.day_plan, "weekday")
        self.assertTrue(plan.collect)
        self.assertFalse(plan.analyze)
        self.assertEqual(plan.report_mode, "daily")
        self.assertEqual(plan.ai_mode, "current")
        self.assertTrue(plan.once_analyze)
        self.assertEqual(plan.frequency_file, "scheduled.txt")
        self.assertEqual(plan.filter_method, "ai")
        self.assertEqual(plan.interests_file, "scheduled-interests.txt")
        with self.assertRaises(FrozenInstanceError):
            plan.report_mode = "current"

    def test_filter_method_falls_back_without_mutating_inputs(self):
        schedule = ResolvedSchedule(
            period_key=None,
            period_name=None,
            day_plan="default",
            collect=True,
            analyze=True,
            report_mode="current",
            ai_mode="follow_report",
            once_analyze=False,
            frequency_file=None,
            filter_method=None,
            interests_file=None,
        )
        config = {"FILTER": {"METHOD": "ai"}}

        first = RunPlanBuilder.build(schedule, config)
        second = RunPlanBuilder.build(schedule, config)

        self.assertEqual(first.filter_method, "ai")
        self.assertIsNone(first.frequency_file)
        self.assertIsNone(first.interests_file)
        self.assertEqual(schedule.filter_method, None)
        self.assertEqual(config, {"FILTER": {"METHOD": "ai"}})
        self.assertIsNot(first, second)

    def test_missing_filter_configuration_uses_keyword(self):
        schedule = ResolvedSchedule(
            period_key=None,
            period_name=None,
            day_plan="default",
            collect=True,
            analyze=True,
            report_mode="incremental",
            ai_mode="follow_report",
            once_analyze=False,
        )

        plan = RunPlanBuilder.build(schedule, {})

        self.assertEqual(plan.filter_method, "keyword")


if __name__ == "__main__":
    unittest.main()
