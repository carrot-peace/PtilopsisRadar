# coding=utf-8
"""Container entrypoint wiring for the Telegram subscription poller."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"


class TestContainerTelegramPoller(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = ENTRYPOINT.read_text(encoding="utf-8")
        cls.cron_branch = cls.source.split('"cron")', 1)[1].split(
            "*)", 1
        )[0]

    def test_disabled_path_preserves_supercronic_as_pid_one(self) -> None:
        self.assertIn(
            'if [ "${PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED:-0}" '
            '!= "1" ]; then',
            self.cron_branch,
        )
        self.assertIn(
            "exec /usr/local/bin/supercronic "
            "-passthrough-logs /tmp/crontab",
            self.cron_branch,
        )

    def test_enabled_path_starts_the_installable_poller_entrypoint(
        self,
    ) -> None:
        self.assertEqual(
            self.cron_branch.count(
                "python -m trendradar.telegram.poller &"
            ),
            1,
        )
        self.assertNotIn(
            "python -m trendradar.telegram.bot",
            self.cron_branch,
        )

    def test_supervisor_waits_for_either_long_running_process(self) -> None:
        self.assertIn(
            'wait -n "$CRON_PID" "$POLLER_PID"',
            self.cron_branch,
        )
        self.assertIn("CHILD_STATUS=$?", self.cron_branch)
        self.assertIn(
            'if [ "$CHILD_STATUS" -eq 0 ]; then',
            self.cron_branch,
        )

    def test_signal_and_child_exit_cleanup_both_processes(self) -> None:
        self.assertIn(
            'kill -TERM "$POLLER_PID" "$CRON_PID"',
            self.cron_branch,
        )
        self.assertIn(
            "trap 'terminate_children; exit 143' TERM INT",
            self.cron_branch,
        )
        self.assertEqual(
            self.cron_branch.count("terminate_children"),
            3,
        )

    def test_once_mode_never_starts_the_poller(self) -> None:
        once_branch = self.source.split('"once")', 1)[1].split(
            '"cron")', 1
        )[0]
        self.assertNotIn("telegram.poller", once_branch)


if __name__ == "__main__":
    unittest.main()
