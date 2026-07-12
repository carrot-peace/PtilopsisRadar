# coding=utf-8
"""Owner-only one-time deployment notification tests."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from trendradar.deployment.notification import (
    DeploymentIdentity,
    TelegramSendResult,
    notify_deployment,
    render_deployment_message,
)


NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)


class FakeSender:
    def __init__(self, failures=()):
        self.failures = set(failures)
        self.calls = []

    def send(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["chat_id"] in self.failures:
            return TelegramSendResult(False, "rejected")
        return TelegramSendResult(True, "telegram_ok")


def _env(**overrides):
    values = {
        "PTILOPSIS_DEPLOYMENT_IMAGE_NAME": "ptilopsis-radar:latest",
        "PTILOPSIS_BUILD_ID": "build-1",
        "PTILOPSIS_BUILD_COMMIT": "abc123",
        "TELEGRAM_BOT_TOKEN": "secret-token",
        "TELEGRAM_OWNER_CHAT_IDS": "111",
        "TELEGRAM_RECEIVER_CHAT_IDS": "999",
    }
    values.update(overrides)
    return values


class TestDeploymentNotification(unittest.TestCase):
    def test_new_identity_sends_only_to_owner_and_writes_safe_state(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            result = notify_deployment(
                _env(), state_path=state, sender=sender, now=NOW
            )

            self.assertEqual(result.status, "sent")
            self.assertEqual([call["chat_id"] for call in sender.calls], ["111"])
            self.assertNotIn("999", [call["chat_id"] for call in sender.calls])
            self.assertNotIn("secret-token", sender.calls[0]["text"])
            state_text = state.read_text(encoding="utf-8")
            self.assertNotIn("secret-token", state_text)
            self.assertNotIn('"111"', state_text)

    def test_restart_same_identity_does_not_duplicate(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            first = notify_deployment(
                _env(), state_path=state, sender=sender, now=NOW
            )
            second = notify_deployment(
                _env(), state_path=state, sender=sender, now=NOW
            )

            self.assertEqual(first.status, "sent")
            self.assertEqual(second.status, "already_notified")
            self.assertEqual(len(sender.calls), 1)

    def test_new_build_identity_sends_again(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            notify_deployment(_env(), state_path=state, sender=sender, now=NOW)
            notify_deployment(
                _env(PTILOPSIS_BUILD_ID="build-2"),
                state_path=state,
                sender=sender,
                now=NOW,
            )
            self.assertEqual(len(sender.calls), 2)

    def test_receiver_only_configuration_never_receives_fallback(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            result = notify_deployment(
                _env(TELEGRAM_OWNER_CHAT_IDS=""),
                state_path=state,
                sender=sender,
                now=NOW,
            )
            self.assertEqual(result.status, "skipped_no_owner")
            self.assertEqual(sender.calls, [])
            self.assertFalse(state.exists())

    def test_failed_delivery_does_not_mark_owner_notified(self):
        sender = FakeSender(failures={"111"})
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            result = notify_deployment(
                _env(), state_path=state, sender=sender, now=NOW
            )
            self.assertEqual(result.status, "partial_failure")
            self.assertEqual(result.failed_owner_count, 1)
            self.assertFalse(state.exists())

    def test_partial_failure_retries_only_missing_owner(self):
        first_sender = FakeSender(failures={"222"})
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            first = notify_deployment(
                _env(TELEGRAM_OWNER_CHAT_IDS="111,222"),
                state_path=state,
                sender=first_sender,
                now=NOW,
            )
            retry_sender = FakeSender()
            second = notify_deployment(
                _env(TELEGRAM_OWNER_CHAT_IDS="111,222"),
                state_path=state,
                sender=retry_sender,
                now=NOW,
            )

            self.assertEqual(first.status, "partial_failure")
            self.assertEqual(second.status, "sent")
            self.assertEqual(
                [call["chat_id"] for call in retry_sender.calls],
                ["222"],
            )
            data = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(len(data["delivered_owner_hashes"]), 2)

    def test_missing_stable_identity_skips_without_state(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            result = notify_deployment(
                _env(
                    PTILOPSIS_BUILD_ID="unknown",
                    PTILOPSIS_BUILD_COMMIT="unknown",
                ),
                state_path=state,
                sender=sender,
                now=NOW,
            )
            self.assertEqual(result.status, "skipped_no_identity")
            self.assertFalse(state.exists())

    def test_message_contains_identity_and_health_without_environment_dump(self):
        text = render_deployment_message(
            DeploymentIdentity(
                image_name="ptilopsis-radar:latest",
                build_id="build-1",
                commit="abc123",
            ),
            started_at="2026-07-12T12:00:00+00:00",
            health="startup checks passed",
        )
        self.assertIn("Image: ptilopsis-radar:latest", text)
        self.assertIn("Image ID: build-1", text)
        self.assertIn("Commit: abc123", text)
        self.assertIn("Health: startup checks passed", text)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", text)


class TestEntrypointWiring(unittest.TestCase):
    def test_notification_runs_once_outside_generated_cron_command(self):
        entrypoint = (
            Path(__file__).resolve().parents[1] / "docker" / "entrypoint.sh"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            entrypoint.count("python -m trendradar.deployment.notification"),
            1,
        )
        crontab_line = next(
            line for line in entrypoint.splitlines()
            if "> /tmp/crontab" in line
        )
        self.assertNotIn("deployment.notification", crontab_line)

    def test_supported_build_paths_inject_stable_deployment_identity(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "docker" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        workflow = (
            root / ".github/workflows/docker-images.yml"
        ).read_text(encoding="utf-8")
        local_build = (
            root / "scripts/apple-container/build-image.zsh"
        ).read_text(encoding="utf-8")

        for name in (
            "PTILOPSIS_BUILD_COMMIT",
            "PTILOPSIS_BUILD_ID",
            "PTILOPSIS_DEPLOYMENT_IMAGE_NAME",
        ):
            self.assertIn(f"ARG {name}", dockerfile)
            self.assertIn(f"{name}=", workflow)
            self.assertIn(f"{name}=", local_build)


if __name__ == "__main__":
    unittest.main()
