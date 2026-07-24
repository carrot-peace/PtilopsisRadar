# coding=utf-8
"""Static container lifecycle guarantees for the Telegram poller."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"


class TestTelegramContainerWiring(unittest.TestCase):
    def test_entrypoint_shell_syntax(self):
        subprocess.run(
            ["bash", "-n", str(ENTRYPOINT)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_once_mode_exits_before_poller_wiring(self):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        once_position = source.index('"once")')
        once_exec_position = source.index(
            "exec python -m trendradar.deployment.run_with_heartbeat",
            once_position,
        )
        poller_position = source.index("python -m trendradar.telegram.bot")
        self.assertLess(once_exec_position, poller_position)

    def test_cron_supervises_both_critical_children_when_enabled(self):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn("PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED", source)
        self.assertIn("python -m trendradar.telegram.bot &", source)
        self.assertIn("supercronic -passthrough-logs /tmp/crontab &", source)
        self.assertIn('wait -n "$CRON_PID" "$BOT_PID"', source)
        self.assertIn("terminate_children", source)

    def test_compose_files_expose_only_canonical_bot_credentials(self):
        for relative_path in (
            "docker/docker-compose.yml",
            "docker/docker-compose-build.yml",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("TELEGRAM_BOT_TOKEN=", source)
            self.assertIn("TELEGRAM_OWNER_CHAT_IDS=", source)
            self.assertIn("PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED=", source)
            self.assertNotIn("PTILOPSIS_CR_TELEGRAM_BOT_TOKEN", source)
            self.assertNotIn("PTILOPSIS_DR_TELEGRAM_BOT_TOKEN", source)
            self.assertNotIn("TELEGRAM_CHAT_ID=", source)


if __name__ == "__main__":
    unittest.main()
