# coding=utf-8
"""Legacy Telegram attachment sender removal tests."""

import unittest
from pathlib import Path

from trendradar.notification import LegacyNotificationRemovedError
from trendradar.notification import send_telegram_document


PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTIFICATION_ROOT = PROJECT_ROOT / "trendradar" / "notification"


class LegacyTelegramAttachmentSenderRemovedTest(unittest.TestCase):
    def test_send_telegram_document_fails_closed(self):
        with self.assertRaises(LegacyNotificationRemovedError):
            send_telegram_document("token", "chat", "report.html")

    def test_notification_package_has_no_telegram_transport_code(self):
        joined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in NOTIFICATION_ROOT.rglob("*.py")
            if "__pycache__" not in path.parts
        )
        for token in (
            "sendMessage",
            "sendDocument",
            "本轮 Telegram 文本简报暂不可用",
        ):
            self.assertNotIn(token, joined)


if __name__ == "__main__":
    unittest.main()
