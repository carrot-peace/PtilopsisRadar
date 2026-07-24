# coding=utf-8
"""CR Telegram config uses the one canonical Bot identity."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trendradar.cr.telegram_env import (
    build_cr_telegram_sink_config_from_env,
    build_cr_telegram_sink_from_env,
    cr_telegram_send_enabled,
)
from trendradar.cr.telegram_sink import CRTelegramSink


class TestCRTelegramEnv(unittest.TestCase):
    def _env(self, **overrides: str) -> dict[str, str]:
        env = {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            "TELEGRAM_BOT_TOKEN": "fake-token",
            "TELEGRAM_OWNER_CHAT_IDS": "11,22",
        }
        env.update(overrides)
        return env

    def test_send_gate_is_exact_one(self):
        self.assertTrue(cr_telegram_send_enabled({"PTILOPSIS_CR_TELEGRAM_SEND": "1"}))
        self.assertFalse(cr_telegram_send_enabled({"PTILOPSIS_CR_TELEGRAM_SEND": " 1 "}))

    def test_disabled_does_not_require_credentials(self):
        self.assertIsNone(build_cr_telegram_sink_config_from_env({}))
        self.assertIsNone(build_cr_telegram_sink_from_env({}))

    def test_canonical_token_and_owner_are_required(self):
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_CHAT_IDS"):
            env = self._env()
            del env[key]
            with self.assertRaises(ValueError) as context:
                build_cr_telegram_sink_config_from_env(env)
            self.assertIn(key, str(context.exception))

    def test_config_uses_canonical_transport_options(self):
        config = build_cr_telegram_sink_config_from_env(
            self._env(
                TELEGRAM_API_BASE_URL="https://telegram.test/",
                TELEGRAM_TIMEOUT_SECONDS="7.5",
                PTILOPSIS_CR_TELEGRAM_PARSE_MODE="HTML",
                PTILOPSIS_CR_TELEGRAM_ATTACH_HTML="0",
                PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW="false",
            )
        )
        assert config is not None
        self.assertEqual(config.api_base_url, "https://telegram.test/")
        self.assertEqual(config.timeout_seconds, 7.5)
        self.assertEqual(config.parse_mode, "HTML")
        self.assertFalse(config.attach_html)
        self.assertFalse(config.disable_web_page_preview)
        self.assertEqual(config.recipients.get_chat_ids(), ("11", "22"))

    def test_subscription_store_is_added_only_when_feature_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "subscriptions.sqlite3"
            config = build_cr_telegram_sink_config_from_env(
                self._env(
                    PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED="1",
                    PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH=str(db),
                )
            )
            assert config is not None
            self.assertTrue(db.exists())
            self.assertEqual(config.recipients.get_chat_ids(), ("11", "22"))

    def test_invalid_shared_timeout_and_bool_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "TELEGRAM_TIMEOUT_SECONDS"):
            build_cr_telegram_sink_config_from_env(
                self._env(TELEGRAM_TIMEOUT_SECONDS="bad")
            )
        with self.assertRaisesRegex(ValueError, "ATTACH_HTML"):
            build_cr_telegram_sink_config_from_env(
                self._env(PTILOPSIS_CR_TELEGRAM_ATTACH_HTML="maybe")
            )

    def test_factory_preserves_injected_client_without_network(self):
        fake = object()
        sink = build_cr_telegram_sink_from_env(self._env(), http_client=fake)  # type: ignore[arg-type]
        self.assertIsInstance(sink, CRTelegramSink)
        assert sink is not None
        self.assertIs(sink.http_client, fake)


if __name__ == "__main__":
    unittest.main()
