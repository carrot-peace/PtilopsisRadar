# coding=utf-8
"""Legacy Telegram attachment sender deletion tests."""

import importlib
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTIFICATION_ROOT = PROJECT_ROOT / "trendradar" / "notification"


class LegacyTelegramAttachmentSenderDeletedTest(unittest.TestCase):
    def test_notification_package_has_no_telegram_transport_code(self):
        self.assertFalse(NOTIFICATION_ROOT.exists())

    def test_send_telegram_document_is_not_importable(self):
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("trendradar.notification")


if __name__ == "__main__":
    unittest.main()
