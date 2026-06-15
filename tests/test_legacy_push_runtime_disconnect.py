# coding=utf-8
"""
PR-A runtime guards for disconnecting Legacy Push from normal execution.

These tests avoid network I/O and do not construct real notification senders.
"""

from __future__ import annotations

import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parent.parent


for _stale in [
    _name
    for _name in list(sys.modules)
    if _name == "trendradar" or _name.startswith("trendradar.")
]:
    del sys.modules[_stale]

import trendradar.__main__ as main  # noqa: E402


class TestLegacyPushRuntimeDisconnect(unittest.TestCase):
    def test_send_notification_entrypoint_fails_closed(self) -> None:
        analyzer = main.NewsAnalyzer.__new__(main.NewsAnalyzer)

        with self.assertRaises(main.LegacyPushRemovedError) as ctx:
            analyzer._send_notification_if_needed(
                stats=[],
                report_type="当前榜单",
                mode="current",
            )

        self.assertIn("Legacy Push has been removed", str(ctx.exception))
        self.assertIn("CR-New canary", str(ctx.exception))

    def test_test_notification_fails_closed_without_dispatcher(self) -> None:
        calls: list[str] = []

        class FakeDispatcher:
            def __init__(self, **kwargs):
                calls.append("init")

            def dispatch_all(self, **kwargs):
                calls.append("dispatch")
                return {"Telegram": True}

        notification_stub = types.ModuleType("trendradar.notification")
        notification_stub.NotificationDispatcher = FakeDispatcher

        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"trendradar.notification": notification_stub}):
            with redirect_stdout(out):
                ok = main._run_test_notification(
                    {
                        "TELEGRAM_BOT_TOKEN": "fake-token",
                        "TELEGRAM_ACCESS": {"receiver_chat_ids": ["fake-chat"]},
                    }
                )

        self.assertFalse(ok)
        self.assertEqual([], calls)
        self.assertIn("Legacy Push has been removed from runtime", out.getvalue())
        self.assertNotIn("测试成功", out.getvalue())

    def test_mode_strategies_do_not_request_notification_send(self) -> None:
        for mode in ("incremental", "current", "daily"):
            with self.subTest(mode=mode):
                self.assertFalse(
                    main.NewsAnalyzer.MODE_STRATEGIES[mode]["should_send_notification"]
                )


if __name__ == "__main__":
    unittest.main()
