# coding=utf-8
"""Focused tests for the notification package facade.

All checks run in isolated subprocesses to avoid polluting sys.modules
in the host test process (which would break mock.patch in Telegram tests).
"""

import subprocess
import sys
import textwrap
import unittest


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


def _run_python(code: str) -> subprocess.CompletedProcess:
    """Run Python code in an isolated subprocess."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
    )


class NotificationFacadeTest(unittest.TestCase):
    def test_positive_exports_remain_available(self):
        names = ", ".join(POSITIVE_EXPORTS)
        result = _run_python(f"""
            import trendradar.notification as notification

            expected = {list(POSITIVE_EXPORTS)}
            missing = [n for n in expected if not hasattr(notification, n)]
            not_in_all = [n for n in expected if n not in notification.__all__]

            if missing:
                raise AssertionError(f"Missing attributes: {{missing}}")
            if not_in_all:
                raise AssertionError(f"Not in __all__: {{not_in_all}}")
        """)
        self.assertEqual(
            result.returncode, 0,
            f"Positive exports check failed:\n{result.stderr}",
        )

    def test_legacy_non_telegram_exports_are_removed(self):
        result = _run_python(f"""
            import trendradar.notification as notification

            removed = {list(REMOVED_EXPORTS)}
            still_present = [n for n in removed if hasattr(notification, n)]
            still_in_all = [n for n in removed if n in notification.__all__]

            errors = []
            if still_present:
                errors.append(f"Still present as attributes: {{still_present}}")
            if still_in_all:
                errors.append(f"Still in __all__: {{still_in_all}}")

            # Verify 'from trendradar.notification import NAME' raises ImportError
            for name in removed:
                try:
                    exec(f"from trendradar.notification import {{name}}")
                    errors.append(f"import {{name}} should have raised ImportError")
                except ImportError:
                    pass

            if errors:
                raise AssertionError("\\n".join(errors))
        """)
        self.assertEqual(
            result.returncode, 0,
            f"Removed exports check failed:\n{result.stderr}",
        )


class AppContextNotificationFacadeTest(unittest.TestCase):
    def test_appcontext_legacy_render_wrappers_removed(self):
        result = _run_python("""
            from trendradar.context import AppContext

            errors = []
            if hasattr(AppContext, "render_feishu"):
                errors.append("AppContext still has render_feishu")
            if hasattr(AppContext, "render_dingtalk"):
                errors.append("AppContext still has render_dingtalk")
            if not hasattr(AppContext, "split_content"):
                errors.append("AppContext missing split_content")

            if errors:
                raise AssertionError("\\n".join(errors))
        """)
        self.assertEqual(
            result.returncode, 0,
            f"AppContext facade check failed:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
