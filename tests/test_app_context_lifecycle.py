# coding=utf-8
"""Resource closing and retention must be separate lifecycle operations."""

import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytz


for _stale in [
    _name
    for _name in list(sys.modules)
    if _name == "trendradar" or _name.startswith("trendradar.")
]:
    del sys.modules[_stale]

from trendradar.application import diagnostics
from trendradar.context import AppContext


class TestAppContextLifecycle(unittest.TestCase):
    def test_close_releases_resources_without_running_retention(self):
        manager = Mock()
        ctx = AppContext({}, storage_manager=manager)

        ctx.close()

        manager.cleanup.assert_called_once_with()
        manager.cleanup_old_data.assert_not_called()
        self.assertIsNone(ctx._storage_manager)

    def test_retention_maintenance_is_explicit(self):
        manager = Mock()
        manager.cleanup_old_data.return_value = 3
        ctx = AppContext({}, storage_manager=manager)

        deleted = ctx.run_retention_maintenance()

        self.assertEqual(deleted, 3)
        manager.cleanup_old_data.assert_called_once_with()
        manager.cleanup.assert_not_called()
        self.assertIs(ctx.get_storage_manager(), manager)

    def test_legacy_cleanup_preserves_combined_behavior(self):
        manager = Mock()
        ctx = AppContext({}, storage_manager=manager)

        ctx.cleanup()

        manager.cleanup_old_data.assert_called_once_with()
        manager.cleanup.assert_called_once_with()
        self.assertIsNone(ctx._storage_manager)

    def test_show_schedule_closes_without_retention(self):
        schedule = SimpleNamespace(
            day_plan="weekday",
            period_key=None,
            period_name=None,
            collect=False,
            analyze=False,
            report_mode="current",
            ai_mode="follow_report",
            once_analyze=False,
        )
        scheduler = SimpleNamespace(resolve=Mock(return_value=schedule))
        ctx = SimpleNamespace(
            create_scheduler=Mock(return_value=scheduler),
            get_time=Mock(
                return_value=datetime(
                    2026, 7, 24, 9, 30, tzinfo=pytz.timezone("Asia/Shanghai")
                )
            ),
            format_date=Mock(return_value="2026-07-24"),
            timezone="Asia/Shanghai",
            close=Mock(),
            cleanup=Mock(),
        )

        with patch.object(
            diagnostics,
            "AppContext",
            return_value=ctx,
        ):
            diagnostics.show_schedule({})

        ctx.close.assert_called_once_with()
        ctx.cleanup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
