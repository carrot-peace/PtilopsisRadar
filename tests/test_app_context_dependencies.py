# coding=utf-8
"""Dependency ownership contracts for AppContext."""

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

from trendradar.context import AppContext
import trendradar.__main__ as application


def _config(data_dir):
    return {
        "TIMEZONE": "Asia/Shanghai",
        "REPORT_MODE": "current",
        "STORAGE": {
            "BACKEND": "local",
            "LOCAL": {"DATA_DIR": data_dir, "RETENTION_DAYS": 0},
            "REMOTE": {"RETENTION_DAYS": 0},
            "FORMATS": {"TXT": True, "HTML": True},
            "PULL": {"ENABLED": False, "DAYS": 0},
        },
        "SCHEDULE": {"enabled": False},
        "_TIMELINE_DATA": {},
    }


class TestAppContextDependencies(unittest.TestCase):
    def test_default_storage_manager_is_owned_per_context(self):
        first = AppContext(_config("output-a"))
        second = AppContext(_config("output-b"))

        first_manager = first.get_storage_manager()
        second_manager = second.get_storage_manager()

        self.assertIsNot(first_manager, second_manager)
        self.assertEqual(first_manager.data_dir, "output-a")
        self.assertEqual(second_manager.data_dir, "output-b")

    def test_injected_manager_bypasses_factory(self):
        manager = Mock()
        factory = Mock()
        ctx = AppContext(
            _config("unused"),
            storage_manager=manager,
            storage_factory=factory,
        )

        self.assertIs(ctx.get_storage_manager(), manager)
        factory.assert_not_called()

    def test_clock_is_the_single_context_time_source(self):
        now = datetime(
            2026,
            7,
            24,
            9,
            5,
            tzinfo=pytz.timezone("Asia/Shanghai"),
        )
        clock = Mock()
        clock.now.return_value = now
        ctx = AppContext(_config("output"), clock=clock)

        self.assertIs(ctx.get_time(), now)
        self.assertEqual(ctx.format_date(), "2026-07-24")
        self.assertEqual(ctx.format_time(), "09-05")
        self.assertEqual(ctx.get_time_display(), "09:05")
        self.assertEqual(clock.now.call_count, 4)
        clock.now.assert_called_with("Asia/Shanghai")

    def test_scheduler_uses_injected_storage_clock_and_factory(self):
        manager = Mock()
        scheduler = object()
        scheduler_factory = Mock(return_value=scheduler)
        clock = Mock()
        ctx = AppContext(
            _config("output"),
            storage_manager=manager,
            scheduler_factory=scheduler_factory,
            clock=clock,
        )

        self.assertIs(ctx.create_scheduler(), scheduler)
        self.assertIs(ctx.create_scheduler(), scheduler)

        scheduler_factory.assert_called_once()
        kwargs = scheduler_factory.call_args.kwargs
        self.assertIs(kwargs["storage_backend"], manager)
        self.assertEqual(kwargs["fallback_report_mode"], "current")
        self.assertEqual(kwargs["get_time_func"](), clock.now.return_value)

    def test_retention_override_targets_only_active_local_backend(self):
        config = _config("output")
        config["STORAGE"]["REMOTE"]["RETENTION_DAYS"] = 45
        ctx = AppContext(config)

        selected = ctx.set_retention_days_for_active_backend(7)
        manager = ctx.get_storage_manager()

        self.assertEqual(selected, "local")
        self.assertEqual(config["STORAGE"]["LOCAL"]["RETENTION_DAYS"], 7)
        self.assertEqual(config["STORAGE"]["REMOTE"]["RETENTION_DAYS"], 45)
        self.assertEqual(manager.local_retention_days, 7)
        self.assertEqual(manager.remote_retention_days, 45)

    def test_retention_override_targets_only_active_remote_backend(self):
        config = _config("output")
        config["STORAGE"]["BACKEND"] = "remote"
        config["STORAGE"]["LOCAL"]["RETENTION_DAYS"] = 20
        config["STORAGE"]["REMOTE"].update(
            {
                "BUCKET_NAME": "bucket",
                "ACCESS_KEY_ID": "access",
                "SECRET_ACCESS_KEY": "secret",
                "ENDPOINT_URL": "https://storage.invalid",
                "REGION": "auto",
            }
        )
        ctx = AppContext(config)

        selected = ctx.set_retention_days_for_active_backend(9)
        manager = ctx.get_storage_manager()

        self.assertEqual(selected, "remote")
        self.assertEqual(config["STORAGE"]["LOCAL"]["RETENTION_DAYS"], 20)
        self.assertEqual(config["STORAGE"]["REMOTE"]["RETENTION_DAYS"], 9)
        self.assertEqual(manager.local_retention_days, 20)
        self.assertEqual(manager.remote_retention_days, 9)

    def test_news_analyzer_applies_environment_retention_to_context(self):
        manager = SimpleNamespace(
            backend_name="local",
            local_retention_days=8,
            remote_retention_days=0,
        )
        ctx = SimpleNamespace(
            set_retention_days_for_active_backend=Mock(return_value="local"),
            get_storage_manager=Mock(return_value=manager),
        )
        analyzer = object.__new__(application.NewsAnalyzer)
        analyzer.ctx = ctx

        with patch.dict(
            "os.environ",
            {"STORAGE_RETENTION_DAYS": "8"},
            clear=False,
        ):
            analyzer._init_storage_manager()

        ctx.set_retention_days_for_active_backend.assert_called_once_with(8)
        self.assertIs(analyzer.storage_manager, manager)


if __name__ == "__main__":
    unittest.main()
