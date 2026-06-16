# coding=utf-8
"""Legacy dispatcher deletion tests."""

import ast
import importlib
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTEXT_PATH = PROJECT_ROOT / "trendradar" / "context.py"
NOTIFICATION_ROOT = PROJECT_ROOT / "trendradar" / "notification"


class LegacyTelegramDispatcherDeletedTest(unittest.TestCase):
    def test_notification_dispatcher_is_not_importable(self):
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("trendradar.notification")

    def test_notification_package_directory_is_absent(self):
        self.assertFalse(NOTIFICATION_ROOT.exists())

    def test_context_exposes_no_dispatcher_factory(self):
        source = CONTEXT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function_names = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        self.assertNotIn("create_notification_dispatcher", function_names)
        self.assertNotIn("NotificationDispatcher", source)


if __name__ == "__main__":
    unittest.main()
