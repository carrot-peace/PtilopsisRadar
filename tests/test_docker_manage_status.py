# coding=utf-8
"""Container process-status checks for cron-only and subscription modes."""

import importlib.util
import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "trendradar_docker_manage_status",
    ROOT / "docker/manage.py",
)
assert SPEC is not None and SPEC.loader is not None
MANAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANAGE)


class TestDockerManageStatus(unittest.TestCase):
    def _show_status(
        self,
        *,
        subscriptions: str,
        cmdlines: dict[int, str],
        children: list[int],
    ) -> tuple[bool, str]:
        with (
            patch.dict(
                os.environ,
                {"PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED": subscriptions},
            ),
            patch.object(
                MANAGE,
                "_read_proc_cmdline",
                side_effect=lambda pid: cmdlines.get(pid, ""),
            ),
            patch.object(
                MANAGE,
                "_read_child_pids",
                return_value=children,
            ),
            redirect_stdout(StringIO()) as output,
        ):
            return MANAGE.show_status(), output.getvalue()

    def test_cron_only_mode_requires_supercronic_as_pid_one(self) -> None:
        healthy, output = self._show_status(
            subscriptions="0",
            cmdlines={1: "/usr/local/bin/supercronic /tmp/crontab"},
            children=[],
        )

        self.assertTrue(healthy)
        self.assertIn("supercronic 正确运行为 PID 1", output)

    def test_subscription_mode_accepts_healthy_supervisor_tree(self) -> None:
        healthy, output = self._show_status(
            subscriptions="1",
            cmdlines={
                1: "/bin/bash /entrypoint.sh",
                20: "/usr/local/bin/supercronic /tmp/crontab",
                21: "python -m trendradar.telegram.poller",
            },
            children=[20, 21],
        )

        self.assertTrue(healthy)
        self.assertIn("entrypoint supervisor 正确运行为 PID 1", output)
        self.assertIn("Telegram poller 子进程运行中", output)

    def test_subscription_mode_fails_when_poller_is_missing(self) -> None:
        healthy, output = self._show_status(
            subscriptions="1",
            cmdlines={
                1: "/bin/bash /entrypoint.sh",
                20: "/usr/local/bin/supercronic /tmp/crontab",
            },
            children=[20],
        )

        self.assertFalse(healthy)
        self.assertIn("未运行 Telegram poller 子进程", output)

    def test_only_exact_one_enables_supervisor_mode(self) -> None:
        healthy, output = self._show_status(
            subscriptions="true",
            cmdlines={1: "/bin/bash /entrypoint.sh"},
            children=[],
        )

        self.assertFalse(healthy)
        self.assertIn("PID 1 不是 supercronic", output)


if __name__ == "__main__":
    unittest.main()
