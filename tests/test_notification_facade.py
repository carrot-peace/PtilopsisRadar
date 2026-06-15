# coding=utf-8
"""Focused tests for the notification package facade.

All checks run in isolated subprocesses to avoid polluting sys.modules
in the host test process (which would break mock.patch in Telegram tests).
"""

import inspect
import subprocess
import sys
import textwrap
import unittest


POSITIVE_EXPORTS = (
    "LegacyNotificationRemovedError",
    "NotificationDispatcher",
    "send_telegram_document",
    "send_to_telegram",
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
    "split_content_into_batches",
    "DEFAULT_BATCH_SIZES",
    "get_batch_header",
    "get_max_batch_header_size",
    "truncate_to_bytes",
    "add_batch_headers",
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

    def test_legacy_public_exports_fail_closed(self):
        result = _run_python("""
            import trendradar.notification as notification

            removed_error = notification.LegacyNotificationRemovedError

            for call in (
                lambda: notification.NotificationDispatcher(config={}, get_time_func=lambda: None),
                lambda: notification.send_to_telegram("token", "chat", {}, "test"),
                lambda: notification.send_telegram_document("token", "chat", "report.html"),
            ):
                try:
                    call()
                except removed_error:
                    pass
                else:
                    raise AssertionError("legacy notification API did not fail closed")
        """)
        self.assertEqual(
            result.returncode, 0,
            f"Fail-closed facade check failed:\n{result.stderr}",
        )

    def test_legacy_sender_stubs_preserve_public_signatures(self):
        from trendradar.notification.senders import (
            resolve_attachment_kind_for_event,
            resolve_report_attachment_path,
            send_telegram_document,
            send_to_telegram,
            should_apply_realtime_alert_gate,
        )

        expected = {
            send_to_telegram: (
                "bot_token",
                "chat_id",
                "report_data",
                "report_type",
                "update_info",
                "proxy_url",
                "mode",
                "account_label",
                "batch_size",
                "batch_interval",
                "rss_items",
                "rss_new_items",
                "ai_analysis",
                "display_regions",
                "html_file_path",
                "get_time_func",
                "alert_state_store",
                "alert_config",
                "manual_trigger",
            ),
            send_telegram_document: (
                "bot_token",
                "chat_id",
                "document_path",
                "filename",
                "caption",
                "proxy_url",
                "max_file_mb",
                "timeout",
                "log_prefix",
            ),
            should_apply_realtime_alert_gate: (
                "report_style",
                "mode",
                "manual_trigger",
            ),
            resolve_attachment_kind_for_event: ("cfg", "event_name"),
            resolve_report_attachment_path: ("output_dir", "mode", "report_kind"),
        }

        for func, names in expected.items():
            with self.subTest(func=func.__name__):
                signature = inspect.signature(func)
                self.assertEqual(names, tuple(signature.parameters))
                for name in ("args", "kwargs"):
                    self.assertNotIn(name, signature.parameters)

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
            if hasattr(AppContext, "split_content"):
                errors.append("AppContext still has split_content")

            if errors:
                raise AssertionError("\\n".join(errors))
        """)
        self.assertEqual(
            result.returncode, 0,
            f"AppContext facade check failed:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
