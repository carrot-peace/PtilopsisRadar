# coding=utf-8
"""Tests for the shared owner-only operator alert boundary."""

import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from trendradar.deployment.operator_alert import (
    TelegramSendResult,
    clear_operator_alert_state,
    load_env_file,
    send_owner_alert,
    send_stateful_owner_alert,
)
from trendradar.deployment.run_with_heartbeat import (
    main as run_with_heartbeat,
    write_heartbeat,
)


class FakeSender:
    def __init__(self, failures=()):
        self.calls = []
        self.failures = set(failures)

    def send(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["chat_id"] in self.failures:
            return TelegramSendResult(False, "rejected")
        return TelegramSendResult(True, "telegram_ok")


class TestOperatorAlert(unittest.TestCase):
    def test_sends_to_explicit_owners(self):
        sender = FakeSender()
        result = send_owner_alert(
            {
                "TELEGRAM_BOT_TOKEN": "secret-token",
                "TELEGRAM_OWNER_CHAT_IDS": "111,222",
            },
            "safe diagnostic",
            sender=sender,
        )
        self.assertEqual(result.status, "sent")
        self.assertEqual(
            [call["chat_id"] for call in sender.calls], ["111", "222"]
        )
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

    def test_stateful_alert_suppresses_per_owner_within_repeat_window(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "secret-token",
            "TELEGRAM_OWNER_CHAT_IDS": "111,222",
        }
        first_sender = FakeSender(failures={"222"})
        retry_sender = FakeSender()
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "alerts.json"
            first = send_stateful_owner_alert(
                env,
                "diagnostic",
                code="http_unhealthy",
                state_path=state,
                repeat_seconds=3600,
                sender=first_sender,
                now=now,
            )
            retry = send_stateful_owner_alert(
                env,
                "diagnostic",
                code="http_unhealthy",
                state_path=state,
                repeat_seconds=3600,
                sender=retry_sender,
                now=now + timedelta(seconds=30),
            )
            suppressed = send_stateful_owner_alert(
                env,
                "diagnostic",
                code="http_unhealthy",
                state_path=state,
                repeat_seconds=3600,
                sender=retry_sender,
                now=now + timedelta(seconds=60),
            )

            self.assertEqual(first.status, "partial_failure")
            self.assertEqual(retry.status, "sent")
            self.assertEqual(
                [call["chat_id"] for call in retry_sender.calls], ["222"]
            )
            self.assertEqual(suppressed.status, "already_notified")
            state_text = state.read_text(encoding="utf-8")
            self.assertNotIn("secret-token", state_text)
            self.assertNotIn('"111"', state_text)

    def test_alert_repeats_after_window_and_health_clear_reopens_incident(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "secret-token",
            "TELEGRAM_OWNER_CHAT_IDS": "111",
        }
        sender = FakeSender()
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "alerts.json"
            for at in (now, now + timedelta(seconds=3601)):
                result = send_stateful_owner_alert(
                    env,
                    "diagnostic",
                    code="http_unhealthy",
                    state_path=state,
                    repeat_seconds=3600,
                    sender=sender,
                    now=at,
                )
                self.assertEqual(result.status, "sent")
            self.assertTrue(clear_operator_alert_state(state, now=now))
            recovered = send_stateful_owner_alert(
                env,
                "diagnostic",
                code="http_unhealthy",
                state_path=state,
                repeat_seconds=3600,
                sender=sender,
                now=now + timedelta(seconds=3700),
            )
            self.assertEqual(recovered.status, "sent")
        self.assertEqual(len(sender.calls), 3)

    def test_malformed_alert_state_is_rotated_before_delivery(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "secret-token",
            "TELEGRAM_OWNER_CHAT_IDS": "111",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "alerts.json"
            state.write_text("{broken", encoding="utf-8")
            result = send_stateful_owner_alert(
                env,
                "diagnostic",
                code="bad_state",
                state_path=state,
                repeat_seconds=3600,
                sender=FakeSender(),
                now=datetime(2026, 7, 13, tzinfo=timezone.utc),
            )
            self.assertEqual(result.status, "sent")
            self.assertTrue(any(root.glob("alerts.json.corrupt.*")))

    def test_future_delivery_epoch_never_suppresses_an_alert(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "secret-token",
            "TELEGRAM_OWNER_CHAT_IDS": "111",
        }
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        owner_hash = hashlib.sha256(b"111").hexdigest()
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "alerts.json"
            state.write_text(
                json.dumps(
                    {
                        "schema_version": "supervisor-alerts-v1",
                        "incidents": {
                            "http_unhealthy": {
                                "delivered_owner_epochs": {
                                    owner_hash: 4_102_444_800,
                                }
                            }
                        },
                        "updated_at": now.isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            result = send_stateful_owner_alert(
                env,
                "diagnostic",
                code="http_unhealthy",
                state_path=state,
                repeat_seconds=3600,
                sender=sender,
                now=now,
            )

        self.assertEqual(result.status, "sent")
        self.assertEqual([call["chat_id"] for call in sender.calls], ["111"])


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
        app = Mock(return_value=0)
        self.assertEqual(run_with_heartbeat(app), 0)
        app.assert_called_once_with()
        heartbeat.assert_called_once_with()

    @patch("trendradar.deployment.run_with_heartbeat.write_heartbeat")
    def test_wrapper_does_not_record_failed_application(self, heartbeat):
        self.assertEqual(run_with_heartbeat(Mock(return_value=7)), 7)
        heartbeat.assert_not_called()

    @patch("trendradar.deployment.run_with_heartbeat.write_heartbeat")
    def test_wrapper_does_not_record_application_exception(self, heartbeat):
        with self.assertRaises(RuntimeError):
            run_with_heartbeat(Mock(side_effect=RuntimeError("failure")))
        heartbeat.assert_not_called()

    def test_concurrent_heartbeat_writes_leave_parseable_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heartbeat.json"
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(lambda _: write_heartbeat(path), range(20)))
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "task-heartbeat-v1")


if __name__ == "__main__":
    unittest.main()
