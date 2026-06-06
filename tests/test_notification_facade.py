# coding=utf-8
"""Focused tests for the notification package facade."""

import importlib
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


POSITIVE_EXPORTS = (
    "NotificationDispatcher",
    "send_to_telegram",
    "split_content_into_batches",
    "DEFAULT_BATCH_SIZES",
    "get_batch_header",
    "get_max_batch_header_size",
    "truncate_to_bytes",
    "add_batch_headers",
    "strip_markdown",
)

REMOVED_EXPORTS = (
    "render_feishu_content",
    "render_dingtalk_content",
    "send_to_feishu",
    "send_to_dingtalk",
    "send_to_wework",
    "send_to_email",
    "send_to_ntfy",
    "send_to_bark",
    "send_to_slack",
    "SMTP_CONFIGS",
    "convert_markdown_to_mrkdwn",
)


def _purge(prefix):
    for name in [m for m in sys.modules if m == prefix or m.startswith(prefix + ".")]:
        del sys.modules[name]


class NotificationFacadeTest(unittest.TestCase):
    def setUp(self):
        _purge("trendradar")

    def tearDown(self):
        _purge("trendradar")

    def test_positive_exports_remain_available(self):
        notification = importlib.import_module("trendradar.notification")

        for name in POSITIVE_EXPORTS:
            with self.subTest(name=name):
                self.assertTrue(hasattr(notification, name))
                self.assertIn(name, notification.__all__)

    def test_legacy_non_telegram_exports_are_removed(self):
        notification = importlib.import_module("trendradar.notification")

        for name in REMOVED_EXPORTS:
            with self.subTest(name=name):
                self.assertFalse(hasattr(notification, name))
                self.assertNotIn(name, notification.__all__)
                with self.assertRaises(ImportError):
                    exec(f"from trendradar.notification import {name}", {})


class AppContextNotificationFacadeTest(unittest.TestCase):
    def setUp(self):
        _purge("trendradar")

    def tearDown(self):
        _purge("trendradar")

    def test_appcontext_import_smoke_and_legacy_render_facade_removed(self):
        from trendradar.context import AppContext

        self.assertFalse(hasattr(AppContext, "render_feishu"))
        self.assertFalse(hasattr(AppContext, "render_dingtalk"))
        self.assertTrue(hasattr(AppContext, "split_content"))


if __name__ == "__main__":
    unittest.main()
