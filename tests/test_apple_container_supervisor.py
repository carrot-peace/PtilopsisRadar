# coding=utf-8
"""Black-box tests for the Apple Container supervisor diagnostics."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
    if [ "${FAKE_CONTAINER_MISSING:-0}" = "1" ] && [ ! -f "$FAKE_CREATED" ]; then
      exit 1
    fi
    [ "${FAKE_INSPECT_SLEEP:-0}" = "0" ] || sleep "$FAKE_INSPECT_SLEEP"
    if [ -f "$FAKE_CREATED" ] || [ -f "$FAKE_STARTED" ]; then
      printf '%s\\n' "$FAKE_AFTER_INSPECT_JSON"
      exit 0
    fi
    printf '%s\\n' "$FAKE_INSPECT_JSON"
    ;;
  run)
    status="${FAKE_RUN_STATUS:-0}"
    [ "$status" = "0" ] && : > "$FAKE_CREATED"
    exit "$status"
    ;;
  start)
    status="${FAKE_START_STATUS:-0}"
    [ "$status" = "0" ] && : > "$FAKE_STARTED"
    exit "$status"
    ;;
esac
exit 0
"""

FAKE_CURL = """#!/bin/sh
exit "${FAKE_CURL_STATUS:-0}"
"""

FAKE_ALERT = """#!/bin/sh
code=""
state=""
clear=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --code) code="$2"; shift 2 ;;
    --state-path) state="$2"; shift 2 ;;
    --clear-state) clear=1; shift ;;
    *) shift ;;
  esac
done
if [ "$clear" = "1" ]; then
  [ -n "$state" ] && rm -f "$state"
  exit 0
fi
if [ -n "$state" ] && [ -f "$state" ] && [ "$(cat "$state")" = "$code" ]; then
  exit 0
fi
printf '%s\\n' "$code" >> "$ALERT_CALLS"
[ -n "$state" ] && printf '%s\\n' "$code" > "$state"
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
        self.daily = self.repo / "output/public/daily/full.html"
        self.current.write_text("ok\n", encoding="utf-8")
        self.daily.write_text("ok\n", encoding="utf-8")

        self.container = self.bin / "container"
        self.curl = self.bin / "curl"
        self.alert = self.bin / "alert-python"
        _write_executable(self.container, FAKE_CONTAINER)
        _write_executable(self.curl, FAKE_CURL)
        _write_executable(self.alert, FAKE_ALERT)
        self.calls = root / "container.calls"
        self.alert_calls = root / "alert.calls"
        self.created_marker = root / "container.created"
        self.started_marker = root / "container.started"
        self.calls.touch()
        self.alert_calls.touch()

        future = datetime.now(timezone.utc) + timedelta(minutes=1)
        created = future.isoformat(timespec="seconds").replace("+00:00", "Z")
        self.write_heartbeat(future)
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

    def write_heartbeat(self, completed_at: datetime) -> None:
        self.heartbeat.write_text(
            json.dumps(
                {
                    "schema_version": "task-heartbeat-v1",
                    "completed_at": completed_at.isoformat(),
                }
            ),
            encoding="utf-8",
        )

    def set_container_times(self, *, started_ago: timedelta) -> None:
        started = datetime.now(timezone.utc) - started_ago
        created = started - timedelta(minutes=1)
        self.inspect_json["configuration"]["creationDate"] = (
            created.isoformat(timespec="seconds").replace("+00:00", "Z")
        )
        self.inspect_json["status"]["startedDate"] = (
            started.isoformat(timespec="seconds").replace("+00:00", "Z")
        )
        env_time = (created - timedelta(minutes=1)).timestamp()
        os.utime(self.env_file, (env_time, env_time))

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
                "FAKE_CREATED": str(self.created_marker),
                "FAKE_STARTED": str(self.started_marker),
                "FAKE_IMAGE_JSON": json.dumps(self.image_json),
                "FAKE_INSPECT_JSON": json.dumps(self.inspect_json),
                "FAKE_AFTER_INSPECT_JSON": json.dumps(
                    {
                        **self.inspect_json,
                        "status": {
                            **self.inspect_json["status"],
                            "state": "running",
                        },
                    }
                ),
                "TREND_RADAR_ALERT_REPEAT": "3600",
                # Normal create/start checks need room for several subprocesses
                # on slower macOS runners. Failure tests override this budget.
                "TREND_RADAR_READINESS_TIMEOUT": "5",
                "TREND_RADAR_READINESS_INTERVAL": "1",
                "TREND_RADAR_COMMAND_TIMEOUT": "2",
                "PYTHONPATH": str(ROOT),
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

    def test_create_and_start_must_be_ready_in_the_same_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            result = fixture.run(FAKE_CONTAINER_MISSING="1")
            self.assertEqual(result.returncode, 0, fixture.supervisor_log())
            self.assertIn("run -d", fixture.calls.read_text())
            self.assertIn("health check passed", fixture.supervisor_log())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            result = fixture.run(
                FAKE_CONTAINER_MISSING="1",
                FAKE_CURL_STATUS="22",
                TREND_RADAR_READINESS_TIMEOUT="1",
            )
            self.assertEqual(result.returncode, 69)
            self.assertIn("container_not_ready", fixture.supervisor_log())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            started = time.monotonic()
            result = fixture.run(
                FAKE_CONTAINER_MISSING="1",
                FAKE_INSPECT_SLEEP="10",
                TREND_RADAR_COMMAND_TIMEOUT="1",
                TREND_RADAR_READINESS_TIMEOUT="2",
            )
            elapsed = time.monotonic() - started
            self.assertEqual(result.returncode, 69)
            self.assertLess(elapsed, 5)
            self.assertIn("container_not_ready", fixture.supervisor_log())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.inspect_json["status"]["state"] = "stopped"
            after = json.loads(json.dumps(fixture.inspect_json))
            after["status"]["state"] = "stopped"
            result = fixture.run(
                FAKE_INSPECT_JSON=json.dumps(fixture.inspect_json),
                FAKE_AFTER_INSPECT_JSON=json.dumps(after),
                TREND_RADAR_READINESS_TIMEOUT="1",
            )
            self.assertEqual(result.returncode, 69)
            self.assertIn("container_not_ready", fixture.supervisor_log())

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
            first = fixture.run()
            self.assertEqual(first.returncode, 0, fixture.supervisor_log())
            original_mtime = fixture.env_file.stat().st_mtime
            fixture.env_file.write_text("CHANGED=safe\n", encoding="utf-8")
            os.utime(fixture.env_file, (original_mtime, original_mtime))
            env_result = fixture.run()
            self.assertEqual(env_result.returncode, 78)
            self.assertIn("env_drift", fixture.supervisor_log())

    def test_missing_env_is_never_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.env_file.unlink()
            result = fixture.run()
            self.assertEqual(result.returncode, 78)
            self.assertIn("env_file_missing", fixture.supervisor_log())

    def test_future_or_reversed_container_identity_is_never_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.inspect_json["configuration"]["creationDate"] = (
                "2099-12-31T23:59:00Z"
            )
            fixture.inspect_json["status"]["startedDate"] = (
                "2100-01-01T00:00:00Z"
            )
            result = fixture.run(
                FAKE_INSPECT_JSON=json.dumps(fixture.inspect_json)
            )
            self.assertEqual(result.returncode, 65)
            self.assertIn("container_identity_missing", fixture.supervisor_log())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            now = datetime.now(timezone.utc)
            fixture.inspect_json["configuration"]["creationDate"] = (
                now.isoformat(timespec="seconds")
            )
            fixture.inspect_json["status"]["startedDate"] = (
                (now - timedelta(minutes=1)).isoformat(timespec="seconds")
            )
            result = fixture.run(
                FAKE_INSPECT_JSON=json.dumps(fixture.inspect_json)
            )
            self.assertEqual(result.returncode, 65)
            self.assertIn("container_identity_missing", fixture.supervisor_log())

    def test_stale_task_and_artifact_are_distinct_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.set_container_times(started_ago=timedelta(hours=2))
            fixture.write_heartbeat(datetime.now(timezone.utc) - timedelta(minutes=2))
            result = fixture.run(TREND_RADAR_MAX_TASK_AGE="60")
            self.assertEqual(result.returncode, 75)
            self.assertIn("task_heartbeat_stale", fixture.supervisor_log())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.set_container_times(started_ago=timedelta(minutes=2))
            fixture.write_heartbeat(datetime.now(timezone.utc))
            stale = (datetime.now().timestamp() - 120)
            os.utime(fixture.current, (stale, stale))
            result = fixture.run(
                TREND_RADAR_MAX_ARTIFACT_AGE="60",
                TREND_RADAR_STARTUP_GRACE="1",
            )
            self.assertEqual(result.returncode, 75)
            self.assertIn("current_artifact_stale", fixture.supervisor_log())

    def test_current_and_daily_artifacts_cannot_mask_each_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.set_container_times(started_ago=timedelta(minutes=2))
            fixture.write_heartbeat(datetime.now(timezone.utc))
            stale = datetime.now().timestamp() - 120
            os.utime(fixture.daily, (stale, stale))
            result = fixture.run(
                TREND_RADAR_MAX_DAILY_ARTIFACT_AGE="60",
                TREND_RADAR_DAILY_STARTUP_GRACE="1",
            )
            self.assertEqual(result.returncode, 75)
            self.assertIn("daily_artifact_stale", fixture.supervisor_log())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.set_container_times(started_ago=timedelta(minutes=2))
            fixture.write_heartbeat(datetime.now(timezone.utc))
            stale = datetime.now().timestamp() - 120
            os.utime(fixture.current, (stale, stale))
            result = fixture.run(
                TREND_RADAR_MAX_CURRENT_ARTIFACT_AGE="60",
                TREND_RADAR_STARTUP_GRACE="1",
            )
            self.assertEqual(result.returncode, 75)
            self.assertIn("current_artifact_stale", fixture.supervisor_log())

    def test_invalid_heartbeat_and_numeric_override_are_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.heartbeat.write_text("{}\n", encoding="utf-8")
            result = fixture.run()
            self.assertEqual(result.returncode, 75)
            self.assertIn("task_heartbeat_invalid", fixture.supervisor_log())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            result = fixture.run(TREND_RADAR_MAX_TASK_AGE="not-a-number")
            self.assertEqual(result.returncode, 64)
            self.assertIn("supervisor_config_invalid", fixture.supervisor_log())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            result = fixture.run(TREND_RADAR_LOG_MAX_BYTES="not-a-number")
            self.assertEqual(result.returncode, 64)
            self.assertIn("supervisor_config_invalid", fixture.supervisor_log())
            self.assertNotIn("bad math expression", result.stderr)

    def test_startup_grace_applies_to_missing_and_stale_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.set_container_times(started_ago=timedelta(minutes=2))
            fixture.heartbeat.unlink()
            fixture.current.unlink()
            within_grace = fixture.run()
            self.assertEqual(
                within_grace.returncode, 0, fixture.supervisor_log()
            )

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.set_container_times(started_ago=timedelta(hours=2))
            fixture.heartbeat.unlink()
            after_grace = fixture.run()
            self.assertEqual(after_grace.returncode, 75)
            self.assertIn("task_heartbeat_missing", fixture.supervisor_log())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            fixture.set_container_times(started_ago=timedelta(minutes=2))
            fixture.write_heartbeat(datetime.now(timezone.utc) - timedelta(minutes=1))
            stale = datetime.now().timestamp() - 120
            os.utime(fixture.current, (stale, stale))
            within_grace = fixture.run(
                TREND_RADAR_MAX_CURRENT_ARTIFACT_AGE="60"
            )
            self.assertEqual(
                within_grace.returncode, 0, fixture.supervisor_log()
            )

    def test_repeat_alert_is_suppressed_until_health_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SupervisorFixture(Path(tmp))
            first = fixture.run(FAKE_CURL_STATUS="22")
            second = fixture.run(FAKE_CURL_STATUS="22")
            self.assertNotEqual(first.returncode, 0)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(
                fixture.alert_calls.read_text().splitlines(), ["http_unhealthy"]
            )
            healthy = fixture.run()
            self.assertEqual(healthy.returncode, 0, fixture.supervisor_log())
            third = fixture.run(FAKE_CURL_STATUS="22")
            self.assertNotEqual(third.returncode, 0)
            self.assertEqual(
                fixture.alert_calls.read_text().splitlines(),
                ["http_unhealthy", "http_unhealthy"],
            )

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
