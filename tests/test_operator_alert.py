# coding=utf-8
"""Tests for the shared owner-only operator alert boundary."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from trendradar.deployment.operator_alert import (
    TelegramSendResult,
    load_env_file,
    send_owner_alert,
)
from trendradar.deployment.run_with_heartbeat import (
    main as run_with_heartbeat,
    write_heartbeat,
)


class FakeSender:
    def __init__(self):
        self.calls = []

    def send(self, **kwargs):
        self.calls.append(kwargs)
        return TelegramSendResult(True, "telegram_ok")


class TestOperatorAlert(unittest.TestCase):
    def test_sends_to_owners_without_receiver_fallback(self):
        sender = FakeSender()
        result = send_owner_alert(
            {
                "TELEGRAM_BOT_TOKEN": "secret-token",
                "TELEGRAM_OWNER_CHAT_IDS": "111,222",
                "TELEGRAM_RECEIVER_CHAT_IDS": "999",
            },
            "safe diagnostic",
            sender=sender,
        )
        self.assertEqual(result.status, "sent")
        self.assertEqual(
            [call["chat_id"] for call in sender.calls], ["111", "222"]
        )
        self.assertNotIn("999", [call["chat_id"] for call in sender.calls])

    def test_requested_subset_cannot_expand_beyond_configured_owners(self):
        sender = FakeSender()
        result = send_owner_alert(
            {
                "TELEGRAM_BOT_TOKEN": "secret-token",
                "TELEGRAM_OWNER_CHAT_IDS": "111",
            },
            "safe diagnostic",
            sender=sender,
            owner_chat_ids=["111", "999"],
        )
        self.assertEqual(result.status, "sent")
        self.assertEqual([call["chat_id"] for call in sender.calls], ["111"])

    def test_env_file_loader_reads_only_operator_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "TELEGRAM_BOT_TOKEN='secret-token'\n"
                "TELEGRAM_OWNER_CHAT_IDS=111\n"
                "UNRELATED_SECRET=do-not-load\n",
                encoding="utf-8",
            )
            values = load_env_file(path)
        self.assertEqual(values["TELEGRAM_BOT_TOKEN"], "secret-token")
        self.assertNotIn("UNRELATED_SECRET", values)


class TestTaskHeartbeat(unittest.TestCase):
    def test_write_heartbeat_is_safe_and_parseable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meta" / "heartbeat.json"
            write_heartbeat(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "task-heartbeat-v1")
        self.assertIn("completed_at", payload)
        self.assertEqual(set(payload), {"schema_version", "completed_at"})

    @patch("trendradar.deployment.run_with_heartbeat.write_heartbeat")
    def test_wrapper_records_completion_after_application(self, heartbeat):
        app = Mock()
        run_with_heartbeat(app)
        app.assert_called_once_with()
        heartbeat.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
