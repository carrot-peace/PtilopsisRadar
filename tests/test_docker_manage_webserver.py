# coding=utf-8

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "trendradar_docker_manage",
    ROOT / "docker/manage.py",
)
assert SPEC is not None and SPEC.loader is not None
MANAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANAGE)


class TestDockerManageWebserver(unittest.TestCase):
    def test_start_webserver_requires_pid_and_http_probe(self):
        process = Mock(pid=4321)
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "web.pid"
            with (
                patch.object(MANAGE, "WEBSERVER_PID_FILE", str(pid_file)),
                patch.object(MANAGE, "_ensure_webserver_root"),
                patch.object(MANAGE.subprocess, "Popen", return_value=process),
                patch.object(MANAGE, "_is_webserver_running", return_value=False),
                patch.object(MANAGE, "_terminate_webserver_process") as terminate,
                patch.object(MANAGE, "_cleanup_stale_pid") as cleanup,
            ):
                self.assertFalse(MANAGE.start_webserver())
            terminate.assert_called_once_with(4321, require_expected=True)
            cleanup.assert_called_once_with()
            self.assertFalse(pid_file.exists())

    def test_start_webserver_returns_true_only_after_probe(self):
        process = Mock(pid=4321)
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "web.pid"
            with (
                patch.object(MANAGE, "WEBSERVER_PID_FILE", str(pid_file)),
                patch.object(MANAGE, "_ensure_webserver_root"),
                patch.object(MANAGE.subprocess, "Popen", return_value=process),
                patch.object(MANAGE, "_is_webserver_running", return_value=True),
            ):
                self.assertTrue(MANAGE.start_webserver())
            self.assertEqual(pid_file.read_text(encoding="utf-8"), "4321")

    def test_cli_propagates_start_failure(self):
        with (
            patch.object(sys, "argv", ["manage.py", "start_webserver"]),
            patch.object(MANAGE, "start_webserver", return_value=False),
        ):
            self.assertEqual(MANAGE.main(), 1)


if __name__ == "__main__":
    unittest.main()
