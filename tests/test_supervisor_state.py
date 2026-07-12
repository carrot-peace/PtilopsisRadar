# coding=utf-8
"""Tests for safe supervisor heartbeat and deployment state."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trendradar.deployment.supervisor_state import (
    check_deployment_state,
    inspect_heartbeat,
)


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


class TestHeartbeatInspection(unittest.TestCase):
    def _write(self, path: Path, completed_at: datetime) -> None:
        path.write_text(
            json.dumps(
                {
                    "schema_version": "task-heartbeat-v1",
                    "completed_at": completed_at.isoformat(),
                }
            ),
            encoding="utf-8",
        )

    def test_fresh_heartbeat_uses_payload_time_not_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heartbeat.json"
            self._write(path, NOW - timedelta(hours=2))
            os.utime(path, (NOW.timestamp(), NOW.timestamp()))
            result = inspect_heartbeat(
                path,
                now_epoch=int(NOW.timestamp()),
                started_epoch=int((NOW - timedelta(days=1)).timestamp()),
                max_age_seconds=60,
            )
        self.assertEqual(result.status, "stale")

    def test_missing_malformed_future_and_prestart_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = inspect_heartbeat(
                root / "missing.json",
                now_epoch=int(NOW.timestamp()),
                started_epoch=int((NOW - timedelta(hours=1)).timestamp()),
                max_age_seconds=60,
            )
            malformed_path = root / "malformed.json"
            malformed_path.write_text("{}", encoding="utf-8")
            malformed = inspect_heartbeat(
                malformed_path,
                now_epoch=int(NOW.timestamp()),
                started_epoch=int((NOW - timedelta(hours=1)).timestamp()),
                max_age_seconds=60,
            )
            future_path = root / "future.json"
            self._write(future_path, NOW + timedelta(hours=1))
            future = inspect_heartbeat(
                future_path,
                now_epoch=int(NOW.timestamp()),
                started_epoch=int((NOW - timedelta(hours=1)).timestamp()),
                max_age_seconds=60,
            )
            prestart_path = root / "prestart.json"
            self._write(prestart_path, NOW - timedelta(minutes=5))
            prestart = inspect_heartbeat(
                prestart_path,
                now_epoch=int(NOW.timestamp()),
                started_epoch=int((NOW - timedelta(minutes=1)).timestamp()),
                max_age_seconds=3600,
            )
        self.assertEqual(missing.status, "missing")
        self.assertEqual(malformed.status, "invalid")
        self.assertEqual(future.status, "future")
        self.assertEqual(prestart.status, "before_start")


class TestDeploymentState(unittest.TestCase):
    def test_baseline_uses_content_hash_and_detects_unchanged_mtime(self):
        created = NOW.isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            state = root / "state.json"
            env_file.write_text("VALUE=one\n", encoding="utf-8")
            old = (NOW - timedelta(hours=1)).timestamp()
            os.utime(env_file, (old, old))
            first = check_deployment_state(
                state,
                env_file=env_file,
                container_created=created,
                image_digest="sha256:same",
                now=NOW,
            )
            original_mtime = env_file.stat().st_mtime
            env_file.write_text("VALUE=two\n", encoding="utf-8")
            os.utime(env_file, (original_mtime, original_mtime))
            second = check_deployment_state(
                state,
                env_file=env_file,
                container_created=created,
                image_digest="sha256:same",
                now=NOW,
            )
            state_text = state.read_text(encoding="utf-8")
        self.assertEqual(first, "baseline_created")
        self.assertEqual(second, "drift")
        self.assertNotIn("VALUE", state_text)

    def test_first_upgrade_refuses_env_newer_than_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            env_file.write_text("VALUE=one\n", encoding="utf-8")
            status = check_deployment_state(
                root / "state.json",
                env_file=env_file,
                container_created=(NOW - timedelta(days=1)).isoformat(),
                image_digest="sha256:same",
                now=NOW,
            )
        self.assertEqual(status, "drift")

    def test_new_container_identity_establishes_new_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            state = root / "state.json"
            env_file.write_text("VALUE=one\n", encoding="utf-8")
            old = (NOW - timedelta(days=2)).timestamp()
            os.utime(env_file, (old, old))
            check_deployment_state(
                state,
                env_file=env_file,
                container_created=(NOW - timedelta(days=1)).isoformat(),
                image_digest="sha256:old",
                now=NOW,
            )
            status = check_deployment_state(
                state,
                env_file=env_file,
                container_created=NOW.isoformat(),
                image_digest="sha256:new",
                now=NOW,
            )
        self.assertEqual(status, "baseline_created")

    def test_new_identity_refuses_env_changed_after_container_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            state = root / "state.json"
            env_file.write_text("VALUE=one\n", encoding="utf-8")
            old = (NOW - timedelta(days=2)).timestamp()
            os.utime(env_file, (old, old))
            check_deployment_state(
                state,
                env_file=env_file,
                container_created=(NOW - timedelta(days=1)).isoformat(),
                image_digest="sha256:old",
                now=NOW,
            )

            env_file.write_text("VALUE=two\n", encoding="utf-8")
            changed_after_creation = (NOW + timedelta(minutes=1)).timestamp()
            os.utime(
                env_file,
                (changed_after_creation, changed_after_creation),
            )
            status = check_deployment_state(
                state,
                env_file=env_file,
                container_created=NOW.isoformat(),
                image_digest="sha256:new",
                now=NOW + timedelta(minutes=2),
            )

        self.assertEqual(status, "drift")


if __name__ == "__main__":
    unittest.main()
