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
            values["PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED"],
            "0",
        )

        for name in (
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_OWNER_CHAT_IDS",
            "TELEGRAM_API_BASE_URL",
            "TELEGRAM_TIMEOUT_SECONDS",
            "PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH",
            "PTILOPSIS_CR_TELEGRAM_PARSE_MODE",
            "PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW",
            "PTILOPSIS_DR_TELEGRAM_ATTACH_HTML",
            "PTILOPSIS_DR_TELEGRAM_PARSE_MODE",
        ):
            self.assertIn(name, values)

    def test_removed_pipeline_credentials_are_absent_everywhere(self):
        removed = (
            "PTILOPSIS_CR_TELEGRAM_BOT_TOKEN",
            "PTILOPSIS_CR_TELEGRAM_CHAT_ID",
            "PTILOPSIS_CR_TELEGRAM_API_BASE_URL",
            "PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS",
            "PTILOPSIS_DR_TELEGRAM_BOT_TOKEN",
            "PTILOPSIS_DR_TELEGRAM_CHAT_ID",
            "PTILOPSIS_DR_TELEGRAM_API_BASE_URL",
            "PTILOPSIS_DR_TELEGRAM_TIMEOUT_SECONDS",
        )
        sources = (
            ROOT / "docker" / ".env.example",
            ROOT / "docker" / "docker-compose.yml",
            ROOT / "docker" / "docker-compose-build.yml",
            ROOT / "docker" / "manage.py",
            ROOT / ".github" / "workflows" / "crawler.yml",
        )
        for path in sources:
            text = path.read_text(encoding="utf-8")
            for name in removed:
                with self.subTest(path=path, name=name):
                    self.assertNotIn(name, text)

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
            self.assertIn(
                "PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED="
                "${PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED:-0}",
                text,
            )
            self.assertIn(
                "TELEGRAM_OWNER_CHAT_IDS=${TELEGRAM_OWNER_CHAT_IDS:-}",
                text,
            )

    def test_mcp_http_defaults_are_loopback_and_read_only(self):
        values = _env_values()
        self.assertEqual(values["MCP_HOST"], "127.0.0.1")
        self.assertEqual(values["MCP_HTTP_ALLOW_WRITE"], "false")
        self.assertEqual(values["MCP_HTTP_BEARER_TOKEN"], "")

        for relative_path in (
            "docker/docker-compose.yml",
            "docker/docker-compose-build.yml",
        ):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn(
                "MCP_HTTP_PUBLISH_HOST=${MCP_HOST:-127.0.0.1}",
                text,
            )
            self.assertIn(
                "MCP_HTTP_ALLOW_WRITE=${MCP_HTTP_ALLOW_WRITE:-false}",
                text,
            )


if __name__ == "__main__":
    unittest.main()
