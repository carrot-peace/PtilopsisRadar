# coding=utf-8
"""Black-box tests for the Apple Container supervisor diagnostics."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = ROOT / "scripts/apple-container/trendradar-supervisor.zsh"
ZSH = shutil.which("zsh")


FAKE_CONTAINER = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_CALLS"
case "$1 $2" in
  "system start") exit 0 ;;
  "image inspect")
    [ "${FAKE_IMAGE_MISSING:-0}" = "1" ] && exit 1
    printf '%s\\n' "$FAKE_IMAGE_JSON"
    ;;
  "logs -n") printf '%s\\n' 'bounded container log';;
esac
case "$1" in
  inspect)
    [ "${FAKE_CONTAINER_MISSING:-0}" = "1" ] && exit 1
    printf '%s\\n' "$FAKE_INSPECT_JSON"
    ;;
  run) exit "${FAKE_RUN_STATUS:-0}" ;;
  start) exit "${FAKE_START_STATUS:-0}" ;;
esac
exit 0
"""

FAKE_CURL = """#!/bin/sh
exit "${FAKE_CURL_STATUS:-0}"
"""

FAKE_ALERT = """#!/bin/sh
printf '%s\\n' "$*" >> "$ALERT_CALLS"
exit 0
"""


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


class SupervisorFixture:
    def __init__(self, root: Path):
        self.repo = root / "repo"
        self.logs = root / "logs"
        self.bin = root / "bin"
        self.repo.mkdir()
        self.logs.mkdir()
        self.bin.mkdir()
        for relative in (
            "docker",
            "config",
            "output/meta",
            "output/public/current",
            "output/public/daily",
        ):
            (self.repo / relative).mkdir(parents=True, exist_ok=True)

        self.env_file = self.repo / "docker/.env"
        self.env_file.write_text(
            "TELEGRAM_BOT_TOKEN=never-log-this-token\n"
            "TELEGRAM_OWNER_CHAT_IDS=111\n",
            encoding="utf-8",
        )
        self.heartbeat = self.repo / "output/meta/last_task_completed.json"
        self.current = self.repo / "output/public/current/index.html"
        self.heartbeat.write_text("{}\n", encoding="utf-8")
        self.current.write_text("ok\n", encoding="utf-8")

        self.container = self.bin / "container"
        self.curl = self.bin / "curl"
        self.alert = self.bin / "alert-python"
        _write_executable(self.container, FAKE_CONTAINER)
        _write_executable(self.curl, FAKE_CURL)
        _write_executable(self.alert, FAKE_ALERT)
        self.calls = root / "container.calls"
        self.alert_calls = root / "alert.calls"
        self.calls.touch()
        self.alert_calls.touch()

        future = datetime.now(timezone.utc) + timedelta(minutes=1)
        created = future.isoformat(timespec="seconds").replace("+00:00", "Z")
        self.image_json = {
            "configuration": {"descriptor": {"digest": "sha256:same"}}
        }
        self.inspect_json = {
            "configuration": {
                "creationDate": created,
                "image": {"descriptor": {"digest": "sha256:same"}},
            },
            "status": {"state": "running", "startedDate": created},
        }

    def environment(self, **overrides: str) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "REPO": str(self.repo),
                "TREND_RADAR_LOG_DIR": str(self.logs),
                "CONTAINER_BIN": str(self.container),
                "CURL_BIN": str(self.curl),
                "JQ_BIN": "/usr/bin/jq",
                "PYTHON_BIN": sys.executable,
                "ALERT_PYTHON_BIN": str(self.alert),
                "FAKE_CALLS": str(self.calls),
                "ALERT_CALLS": str(self.alert_calls),
                "FAKE_IMAGE_JSON": json.dumps(self.image_json),
                "FAKE_INSPECT_JSON": json.dumps(self.inspect_json),
                "TREND_RADAR_ALERT_REPEAT": "3600",
            }
        )
        env.update(overrides)
        return env

    def run(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [ZSH or "zsh", str(SUPERVISOR), "--once"],
            env=self.environment(**overrides),
            text=True,
            capture_output=True,
            check=False,
        )

    def supervisor_log(self) -> str:
        path = self.logs / "trendradar-supervisor.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""


@unittest.skipUnless(ZSH, "Apple Container supervisor tests require zsh")
class TestAppleContainerSupervisor(unittest.TestCase):
    def test_healthy_once_check_covers_endpoint_and_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            result = fixture.run()
            self.assertEqual(result.returncode, 0, fixture.supervisor_log())
            self.assertIn("health check passed", fixture.supervisor_log())
            self.assertIn("logs -n 500 trendradar", fixture.calls.read_text())
            self.assertEqual(fixture.alert_calls.read_text(), "")

    def test_http_failure_is_nonzero_and_alerts_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            result = fixture.run(FAKE_CURL_STATUS="22")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("http_unhealthy", fixture.supervisor_log())
            self.assertIn("http_unhealthy", fixture.alert_calls.read_text())
            combined = fixture.supervisor_log() + fixture.alert_calls.read_text()
            self.assertNotIn("never-log-this-token", combined)

    def test_missing_local_image_never_attempts_container_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            result = fixture.run(FAKE_IMAGE_MISSING="1")
            self.assertNotEqual(result.returncode, 0)
            calls = fixture.calls.read_text(encoding="utf-8")
            self.assertIn("image inspect ptilopsis-radar:latest", calls)
            self.assertNotIn("run -d", calls)
            self.assertIn("local_image_missing", fixture.alert_calls.read_text())

    def test_create_and_start_failures_alert_and_return_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            result = fixture.run(
                FAKE_CONTAINER_MISSING="1",
                FAKE_RUN_STATUS="1",
            )
            self.assertEqual(result.returncode, 70)
            self.assertIn("container_create_failed", fixture.alert_calls.read_text())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.inspect_json["status"]["state"] = "stopped"
            result = fixture.run(
                FAKE_INSPECT_JSON=json.dumps(fixture.inspect_json),
                FAKE_START_STATUS="1",
            )
            self.assertEqual(result.returncode, 70)
            self.assertIn("container_start_failed", fixture.alert_calls.read_text())

    def test_env_and_image_drift_require_recreate(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.inspect_json["configuration"]["image"]["descriptor"][
                "digest"
            ] = "sha256:old"
            image_result = fixture.run(
                FAKE_INSPECT_JSON=json.dumps(fixture.inspect_json)
            )
            self.assertEqual(image_result.returncode, 78)
            self.assertIn("image_drift", fixture.supervisor_log())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            old = datetime.now(timezone.utc) - timedelta(hours=1)
            fixture.inspect_json["configuration"]["creationDate"] = (
                old.isoformat(timespec="seconds").replace("+00:00", "Z")
            )
            env_result = fixture.run(
                FAKE_INSPECT_JSON=json.dumps(fixture.inspect_json)
            )
            self.assertEqual(env_result.returncode, 78)
            self.assertIn("env_drift", fixture.supervisor_log())

    def test_stale_task_and_artifact_are_distinct_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            stale = (datetime.now().timestamp() - 120)
            os.utime(fixture.heartbeat, (stale, stale))
            result = fixture.run(TREND_RADAR_MAX_TASK_AGE="60")
            self.assertEqual(result.returncode, 75)
            self.assertIn("task_heartbeat_stale", fixture.supervisor_log())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            stale = (datetime.now().timestamp() - 120)
            os.utime(fixture.current, (stale, stale))
            result = fixture.run(TREND_RADAR_MAX_ARTIFACT_AGE="60")
            self.assertEqual(result.returncode, 75)
            self.assertIn("artifact_stale", fixture.supervisor_log())

    def test_supervisor_and_container_log_snapshots_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            supervisor_log = fixture.logs / "trendradar-supervisor.log"
            supervisor_log.write_text("old-supervisor-log\n", encoding="utf-8")
            first = fixture.run(TREND_RADAR_LOG_MAX_BYTES="1")
            self.assertEqual(first.returncode, 0)
            second = fixture.run(TREND_RADAR_LOG_MAX_BYTES="100000")
            self.assertEqual(second.returncode, 0)
            self.assertTrue(any(fixture.logs.glob("trendradar-supervisor.log.*")))
            self.assertTrue(
                (fixture.logs / "trendradar-container.log.1").exists()
            )


if __name__ == "__main__":
    unittest.main()
