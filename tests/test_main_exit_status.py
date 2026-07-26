# coding=utf-8
"""Regression tests for scheduled application exit status propagation."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Several lightweight test modules install partial ``trendradar`` package
# stubs during collection.  This test needs the real application package, so
# make that import independent of test collection order.
for _stale in [
    _name
    for _name in list(sys.modules)
    if _name == "trendradar" or _name.startswith("trendradar.")
]:
    del sys.modules[_stale]

import trendradar.__main__ as application
from trendradar.deployment.run_with_heartbeat import main as run_with_heartbeat


class TestMainExitStatus(unittest.TestCase):
    def _analyzer_with_internal_failure(self):
        analyzer = object.__new__(application.NewsAnalyzer)
        analyzer.ctx = SimpleNamespace(
            config={"DEBUG": False},
            run_retention_maintenance=Mock(),
            close=Mock(),
            cleanup=Mock(),
        )
        analyzer.is_github_actions = False
        analyzer._initialize_and_check_config = Mock(return_value=True)
        analyzer._resolve_run_plan = Mock(
            return_value=SimpleNamespace(collect=True)
        )
        analyzer._crawl_data = Mock(side_effect=RuntimeError("crawl failed"))
        analyzer._cr_hotlist_successful_ids = set()
        analyzer._cr_hotlist_failed_ids = set()
        analyzer._cr_rss_successful_ids = set()
        analyzer._cr_rss_failed_ids = set()
        analyzer._cr_observed_item_identities = set()
        return analyzer

    @patch.object(application, "load_config", side_effect=FileNotFoundError("missing"))
    @patch("sys.argv", ["trendradar"])
    def test_missing_config_returns_nonzero(self, _load_config):
        self.assertEqual(application.main(), 1)

    @patch.object(application, "load_config", return_value={})
    @patch("sys.argv", ["trendradar"])
    def test_successful_run_returns_zero(self, _load_config):
        analyzer = Mock()
        analyzer.is_github_actions = False
        analyzer.ctx = SimpleNamespace(config={"DEBUG": False})
        with patch.object(application, "NewsAnalyzer", return_value=analyzer):
            self.assertEqual(application.main(), 0)
        analyzer.run.assert_called_once_with()

    @patch.object(application, "load_config", return_value={})
    @patch("sys.argv", ["trendradar"])
    def test_non_debug_runtime_failure_returns_nonzero(self, _load_config):
        analyzer = Mock()
        analyzer.is_github_actions = False
        analyzer.ctx = SimpleNamespace(config={"DEBUG": False})
        analyzer.run.side_effect = RuntimeError("failed")
        with patch.object(application, "NewsAnalyzer", return_value=analyzer):
            self.assertEqual(application.main(), 1)

    @patch.object(application, "load_config", return_value={})
    @patch("sys.argv", ["trendradar"])
    def test_debug_runtime_failure_still_raises(self, _load_config):
        analyzer = Mock()
        analyzer.is_github_actions = False
        analyzer.ctx = SimpleNamespace(config={"DEBUG": True})
        analyzer.run.side_effect = RuntimeError("failed")
        with patch.object(application, "NewsAnalyzer", return_value=analyzer):
            with self.assertRaises(RuntimeError):
                application.main()

    @patch.object(application, "load_config", return_value={})
    @patch("sys.argv", ["trendradar"])
    def test_internal_pipeline_failure_does_not_write_heartbeat(self, _load_config):
        analyzer = self._analyzer_with_internal_failure()
        with (
            patch.object(application, "NewsAnalyzer", return_value=analyzer),
            patch(
                "trendradar.deployment.run_with_heartbeat.write_heartbeat"
            ) as heartbeat,
        ):
            self.assertEqual(run_with_heartbeat(application.main), 1)
        heartbeat.assert_not_called()
        analyzer.ctx.run_retention_maintenance.assert_called_once_with()
        analyzer.ctx.close.assert_called_once_with()
        analyzer.ctx.cleanup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
