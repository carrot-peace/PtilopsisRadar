# coding=utf-8
"""Legacy Telegram alert sender deletion tests."""

import importlib
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTIFICATION_ROOT = PROJECT_ROOT / "trendradar" / "notification"


class LegacyTelegramAlertSenderDeletedTest(unittest.TestCase):
    def test_legacy_sender_module_is_deleted(self):
        self.assertFalse((NOTIFICATION_ROOT / "senders.py").exists())

    def test_send_to_telegram_is_not_importable(self):
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("trendradar.notification.senders")

    def test_old_fallback_text_is_not_in_runtime_code(self):
        offenders = []
        for path in (PROJECT_ROOT / "trendradar").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            if "本轮 Telegram 文本简报暂不可用" in source:
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
