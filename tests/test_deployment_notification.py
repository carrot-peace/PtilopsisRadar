# coding=utf-8
"""Owner-only one-time deployment notification tests."""

import hashlib
import json
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from trendradar.deployment.notification import (
    DeploymentIdentity,
    TelegramSendResult,
    identity_from_env,
    notify_deployment,
    render_deployment_message,
)


NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
HEALTH = "config files present, cron syntax OK, web HTTP OK"


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
    }
    values.update(overrides)
    return values


def _notify(env, **kwargs):
    return notify_deployment(env, health=HEALTH, **kwargs)


class TestDeploymentNotification(unittest.TestCase):
    def test_new_identity_sends_only_to_owner_and_writes_safe_state(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            result = _notify(
                _env(), state_path=state, sender=sender, now=NOW
            )

            self.assertEqual(result.status, "sent")
            self.assertEqual([call["chat_id"] for call in sender.calls], ["111"])
            self.assertNotIn("secret-token", sender.calls[0]["text"])
            state_text = state.read_text(encoding="utf-8")
            self.assertNotIn("secret-token", state_text)
            self.assertNotIn('"111"', state_text)

    def test_restart_same_identity_does_not_duplicate(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            first = _notify(
                _env(), state_path=state, sender=sender, now=NOW
            )
            second = _notify(
                _env(), state_path=state, sender=sender, now=NOW
            )

            self.assertEqual(first.status, "sent")
            self.assertEqual(second.status, "already_notified")
            self.assertEqual(len(sender.calls), 1)

    def test_new_build_identity_sends_again(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            _notify(_env(), state_path=state, sender=sender, now=NOW)
            _notify(
                _env(PTILOPSIS_BUILD_ID="build-2"),
                state_path=state,
                sender=sender,
                now=NOW,
            )
            self.assertEqual(len(sender.calls), 2)

    def test_identity_history_prevents_a_b_a_duplicate(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            _notify(
                _env(PTILOPSIS_BUILD_ID="build-a"),
                state_path=state,
                sender=sender,
                now=NOW,
            )
            _notify(
                _env(PTILOPSIS_BUILD_ID="build-b"),
                state_path=state,
                sender=sender,
                now=NOW,
            )
            result = _notify(
                _env(PTILOPSIS_BUILD_ID="build-a"),
                state_path=state,
                sender=sender,
                now=NOW,
            )

            self.assertEqual(result.status, "already_notified")
            self.assertEqual(len(sender.calls), 2)
            data = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], "deployment-notification-v2")
            self.assertEqual(len(data["identities"]), 2)

    def test_missing_owner_configuration_skips(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            result = _notify(
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
            result = _notify(
                _env(), state_path=state, sender=sender, now=NOW
            )
            self.assertEqual(result.status, "partial_failure")
            self.assertEqual(result.failed_owner_count, 1)
            self.assertFalse(state.exists())

    def test_partial_failure_retries_only_missing_owner(self):
        first_sender = FakeSender(failures={"222"})
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            first = _notify(
                _env(TELEGRAM_OWNER_CHAT_IDS="111,222"),
                state_path=state,
                sender=first_sender,
                now=NOW,
            )
            retry_sender = FakeSender()
            second = _notify(
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
            identity_entry = next(iter(data["identities"].values()))
            self.assertEqual(len(identity_entry["delivered_owner_hashes"]), 2)

    def test_missing_stable_identity_skips_without_state(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            result = _notify(
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

    def test_v1_state_migrates_without_resending(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            identity_key = identity_from_env(_env()).key
            state.write_text(
                json.dumps(
                    {
                        "schema_version": "deployment-notification-v1",
                        "identity_key": identity_key,
                        "delivered_owner_hashes": [
                            hashlib.sha256(b"111").hexdigest()
                        ],
                        "updated_at": NOW.isoformat(),
                    }
                ),
                encoding="utf-8",
            )

            result = _notify(
                _env(), state_path=state, sender=sender, now=NOW
            )

            self.assertEqual(result.status, "already_notified")
            self.assertEqual(sender.calls, [])
            migrated = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(
                migrated["schema_version"], "deployment-notification-v2"
            )
            self.assertIn(identity_key, migrated["identities"])

    def test_malformed_state_fails_closed_without_overwrite(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            state.write_text("{broken", encoding="utf-8")

            result = _notify(
                _env(), state_path=state, sender=sender, now=NOW
            )

            self.assertEqual(result.status, "failed_invalid_state")
            self.assertEqual(sender.calls, [])
            self.assertEqual(state.read_text(encoding="utf-8"), "{broken")

    def test_unknown_state_schema_fails_closed_without_overwrite(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            original = '{"schema_version":"deployment-notification-v99"}'
            state.write_text(original, encoding="utf-8")

            result = _notify(
                _env(), state_path=state, sender=sender, now=NOW
            )

            self.assertEqual(result.status, "failed_invalid_state")
            self.assertEqual(sender.calls, [])
            self.assertEqual(state.read_text(encoding="utf-8"), original)

    def test_invalid_hashes_fail_closed_without_overwrite(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            identity_key = identity_from_env(_env()).key
            invalid_owner = json.dumps(
                {
                    "schema_version": "deployment-notification-v2",
                    "identities": {
                        identity_key: {
                            "delivered_owner_hashes": ["corrupt"],
                            "updated_at": NOW.isoformat(),
                        }
                    },
                    "updated_at": NOW.isoformat(),
                }
            )
            state.write_text(invalid_owner, encoding="utf-8")
            result = _notify(
                _env(), state_path=state, sender=sender, now=NOW
            )
            self.assertEqual(result.status, "failed_invalid_state")
            self.assertEqual(sender.calls, [])
            self.assertEqual(state.read_text(encoding="utf-8"), invalid_owner)

            invalid_identity = invalid_owner.replace(identity_key, "not-a-hash")
            state.write_text(invalid_identity, encoding="utf-8")
            result = _notify(
                _env(), state_path=state, sender=sender, now=NOW
            )
            self.assertEqual(result.status, "failed_invalid_state")
            self.assertEqual(sender.calls, [])
            self.assertEqual(state.read_text(encoding="utf-8"), invalid_identity)

    def test_concurrent_same_identity_sends_once(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"

            def run_once():
                return _notify(
                    _env(), state_path=state, sender=sender, now=NOW
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: run_once(), range(2)))

            self.assertEqual(len(sender.calls), 1)
            self.assertEqual(
                sorted(result.status for result in results),
                ["already_notified", "sent"],
            )

    def test_missing_explicit_health_never_sends_or_writes_state(self):
        sender = FakeSender()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            result = notify_deployment(
                _env(), health="", state_path=state, sender=sender, now=NOW
            )
            self.assertEqual(result.status, "failed_missing_health")
            self.assertEqual(sender.calls, [])
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
        cron_start = entrypoint.index('"cron")')
        default_start = entrypoint.index('*)', cron_start)
        notification = entrypoint.index(
            "python -m trendradar.deployment.notification"
        )
        self.assertGreater(notification, cron_start)
        self.assertLess(notification, default_start)
        self.assertGreater(notification, entrypoint.index("supercronic -test"))
        self.assertGreater(notification, entrypoint.index("start_webserver"))
        self.assertIn(
            '--health "config files present, cron syntax OK, web HTTP OK"',
            entrypoint,
        )

        manage = (
            Path(__file__).resolve().parents[1] / "docker" / "manage.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_is_webserver_running(process.pid)", manage)
        self.assertIn("return 1 if result is False else 0", manage)

    def test_supported_build_paths_inject_stable_deployment_identity(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "docker" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        workflow = (
            root / ".github/workflows/docker-images.yml"
        ).read_text(encoding="utf-8")
        pr_workflow = (
            root / ".github/workflows/docker-pr.yml"
        ).read_text(encoding="utf-8")
        local_build = (
            root / "scripts/apple-container/build-image.zsh"
        ).read_text(encoding="utf-8")
        compose = (root / "docker/docker-compose-build.yml").read_text(
            encoding="utf-8"
        )
        compose_build = root / "scripts/docker/build-image.sh"
        compose_build_text = compose_build.read_text(encoding="utf-8")

        for name in (
            "PTILOPSIS_BUILD_COMMIT",
            "PTILOPSIS_BUILD_ID",
            "PTILOPSIS_DEPLOYMENT_IMAGE_NAME",
        ):
            self.assertIn(f"ARG {name}", dockerfile)
            self.assertIn(f"{name}=", workflow)
            self.assertIn(f"{name}=", pr_workflow)
            self.assertIn(f"{name}=", local_build)
            self.assertIn(f"{name}:", compose)
            self.assertIn(f"{name}=", compose_build_text)
            self.assertIn(f'test "${{{name}}}" != "unknown"', dockerfile)

        self.assertIn(
            "ARG PTILOPSIS_DEPLOYMENT_IMAGE_NAME=unknown",
            dockerfile,
        )

        self.assertIn("uuidgen", local_build)
        self.assertTrue(compose_build.stat().st_mode & stat.S_IXUSR)
        self.assertIn(
            "git status --porcelain --untracked-files=normal",
            compose_build_text,
        )
        self.assertIn(
            'PTILOPSIS_BUILD_COMMIT="${PTILOPSIS_BUILD_COMMIT}-dirty"',
            compose_build_text,
        )
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "scripts/apple-container/build-image.zsh ptilopsis-radar:latest",
            readme,
        )
        self.assertIn(
            "scripts/docker/build-image.sh wantcat/trendradar:latest",
            readme,
        )
        self.assertNotIn(
            "container build --arch arm64 --tag ptilopsis-radar:latest",
            readme,
        )
        readme_cn = (root / "README-CN.md").read_text(encoding="utf-8")
        self.assertIn(
            "scripts/apple-container/build-image.zsh ptilopsis-radar:latest",
            readme_cn,
        )
        self.assertNotIn(
            "container build --arch arm64 --tag ptilopsis-radar:latest",
            readme_cn,
        )
        self.assertNotIn(":?run scripts/docker/build-image.sh", compose)


if __name__ == "__main__":
    unittest.main()
