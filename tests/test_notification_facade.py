# coding=utf-8
"""Legacy notification package deletion tests."""

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTIFICATION_ROOT = PROJECT_ROOT / "trendradar" / "notification"


def _run_python(code: str) -> subprocess.CompletedProcess:
    """Run Python code in an isolated subprocess."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )


class NotificationPackageDeletedTest(unittest.TestCase):
    def test_notification_package_directory_is_absent(self):
        self.assertFalse(NOTIFICATION_ROOT.exists())

    def test_notification_package_import_fails(self):
        result = _run_python("""
            import importlib
            import sys

            for name in list(sys.modules):
                if name == "trendradar.notification" or name.startswith("trendradar.notification."):
                    del sys.modules[name]

            try:
                importlib.import_module("trendradar.notification")
            except ModuleNotFoundError as exc:
                if exc.name != "trendradar.notification":
                    raise
            else:
                raise AssertionError("trendradar.notification should be deleted")
        """)
        self.assertEqual(
            result.returncode,
            0,
            f"Deleted package import check failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )

    def test_legacy_public_imports_fail(self):
        result = _run_python("""
            names = [
                "LegacyNotificationRemovedError",
                "NotificationDispatcher",
                "send_telegram_document",
                "send_to_telegram",
                "strip_markdown",
            ]

            for name in names:
                try:
                    exec(f"from trendradar.notification import {name}")
                except ModuleNotFoundError as exc:
                    if exc.name != "trendradar.notification":
                        raise
                else:
                    raise AssertionError(f"{name} imported from deleted package")
        """)
        self.assertEqual(
            result.returncode,
            0,
            f"Deleted export check failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )


class AppContextNotificationFacadeTest(unittest.TestCase):
    def test_appcontext_notification_factory_removed(self):
        result = _run_python("""
            from trendradar.context import AppContext

            removed = [
                "create_notification_dispatcher",
                "render_feishu",
                "render_dingtalk",
                "split_content",
            ]
            still_present = [name for name in removed if hasattr(AppContext, name)]

            if still_present:
                raise AssertionError(f"AppContext still exposes legacy notification API: {still_present}")
        """)
        self.assertEqual(
            result.returncode,
            0,
            f"AppContext facade check failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
