# coding=utf-8
"""Legacy Telegram alert sender removal tests."""

import unittest
from pathlib import Path

from trendradar.notification import LegacyNotificationRemovedError
from trendradar.notification import send_to_telegram
from trendradar.notification.senders import should_apply_realtime_alert_gate


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SENDERS_PATH = PROJECT_ROOT / "trendradar" / "notification" / "senders.py"


class LegacyTelegramAlertSenderRemovedTest(unittest.TestCase):
    def test_send_to_telegram_fails_closed(self):
        with self.assertRaises(LegacyNotificationRemovedError):
            send_to_telegram("token", "chat", {}, "test")

    def test_realtime_alert_gate_helper_fails_closed(self):
        with self.assertRaises(LegacyNotificationRemovedError):
            should_apply_realtime_alert_gate("environment", "current")

    def test_old_fallback_text_is_not_in_sender_code(self):
        source = SENDERS_PATH.read_text(encoding="utf-8")
        self.assertNotIn("本轮 Telegram 文本简报暂不可用", source)
        self.assertNotIn("fallback", source.lower())


if __name__ == "__main__":
    unittest.main()
