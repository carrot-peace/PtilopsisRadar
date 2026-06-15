# coding=utf-8
"""Legacy dispatcher removal tests."""

import unittest

from trendradar.notification import LegacyNotificationRemovedError, NotificationDispatcher


class LegacyTelegramDispatcherRemovedTest(unittest.TestCase):
    def test_dispatcher_constructor_fails_closed(self):
        with self.assertRaises(LegacyNotificationRemovedError):
            NotificationDispatcher(config={}, get_time_func=lambda: None)

    def test_dispatch_all_fails_closed_if_stale_instance_exists(self):
        dispatcher = object.__new__(NotificationDispatcher)
        with self.assertRaises(LegacyNotificationRemovedError):
            dispatcher.dispatch_all({}, "test")

    def test_private_telegram_send_fails_closed_if_stale_instance_exists(self):
        dispatcher = object.__new__(NotificationDispatcher)
        with self.assertRaises(LegacyNotificationRemovedError):
            dispatcher._send_telegram({}, "test", None, None, "daily")

    def test_translate_content_fails_closed(self):
        dispatcher = object.__new__(NotificationDispatcher)
        with self.assertRaises(LegacyNotificationRemovedError):
            dispatcher.translate_content({})


if __name__ == "__main__":
    unittest.main()
