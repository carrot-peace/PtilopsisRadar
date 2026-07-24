# coding=utf-8
"""Container environment example must not silently override AI config defaults."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


def _env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in (ROOT / "docker" / ".env.example").read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


class TestDockerEnvExample(unittest.TestCase):
    def test_shared_ai_config_knobs_default_to_blank(self):
        values = _env_values()
        self.assertEqual(values["AI_ANALYSIS_ENABLED"], "")
        self.assertEqual(values["AI_MODEL"], "")
        self.assertEqual(values["AI_API_KEY"], "")
        self.assertEqual(values["AI_API_BASE"], "")

    def test_dispatch_defaults_are_safe_and_complete(self):
        values = _env_values()
        self.assertEqual(values["PTILOPSIS_CR_DISPATCH_MODE"], "off")
        self.assertEqual(values["PTILOPSIS_CR_TELEGRAM_SEND"], "0")
        self.assertEqual(values["PTILOPSIS_DR_DISPATCH_MODE"], "off")
        self.assertEqual(values["PTILOPSIS_DR_TELEGRAM_SEND"], "0")
        self.assertEqual(
            values["PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED"], "0"
        )

        for name in (
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_OWNER_CHAT_IDS",
            "TELEGRAM_API_BASE_URL",
            "TELEGRAM_TIMEOUT_SECONDS",
            "PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH",
            "PTILOPSIS_CR_TELEGRAM_ATTACH_HTML",
            "PTILOPSIS_CR_TELEGRAM_PARSE_MODE",
            "PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW",
        ):
            self.assertIn(name, values)

        for removed_name in (
            "TELEGRAM_CHAT_ID",
            "PTILOPSIS_CR_TELEGRAM_BOT_TOKEN",
            "PTILOPSIS_CR_TELEGRAM_CHAT_ID",
            "PTILOPSIS_DR_TELEGRAM_BOT_TOKEN",
            "PTILOPSIS_DR_TELEGRAM_CHAT_ID",
        ):
            self.assertNotIn(removed_name, values)

    def test_compose_files_honor_configured_timezone(self):
        for relative_path in (
            "docker/docker-compose.yml",
            "docker/docker-compose-build.yml",
        ):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("TZ=${TZ:-Asia/Shanghai}", text)
            self.assertIn(
                "PTILOPSIS_CR_DISPATCH_MODE=${PTILOPSIS_CR_DISPATCH_MODE:-off}",
                text,
            )


if __name__ == "__main__":
    unittest.main()
