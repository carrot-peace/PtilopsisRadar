# coding=utf-8
"""CR Telegram configuration uses the canonical Bot identity."""

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


FAKE_TOKEN = "FAKE-CR-TOKEN-000:abc"


class TestCRTelegramEnv(unittest.TestCase):
    def _env(self, **overrides: str) -> dict[str, str]:
        env = {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            "TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
            "TELEGRAM_OWNER_CHAT_IDS": "11,22",
        }
        env.update(overrides)
        return env

    def test_send_gate_is_exact_one(self) -> None:
        self.assertTrue(
            cr_telegram_send_enabled(
                {"PTILOPSIS_CR_TELEGRAM_SEND": "1"}
            )
        )
        self.assertFalse(
            cr_telegram_send_enabled(
                {"PTILOPSIS_CR_TELEGRAM_SEND": " 1 "}
            )
        )

    def test_disabled_does_not_require_credentials_or_create_database(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "subscriptions.sqlite3"
            env = {
                "PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED": "1",
                "PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH": str(db),
            }
            self.assertIsNone(
                build_cr_telegram_sink_config_from_env(env)
            )
            self.assertIsNone(build_cr_telegram_sink_from_env(env))
            self.assertFalse(db.exists())

    def test_canonical_token_and_owner_are_required(self) -> None:
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_CHAT_IDS"):
            with self.subTest(key=key):
                env = self._env()
                del env[key]
                with self.assertRaisesRegex(ValueError, key):
                    build_cr_telegram_sink_config_from_env(env)

    def test_legacy_pipeline_credentials_are_not_fallbacks(self) -> None:
        with self.assertRaisesRegex(ValueError, "TELEGRAM_BOT_TOKEN"):
            build_cr_telegram_sink_config_from_env(
                {
                    "PTILOPSIS_CR_TELEGRAM_SEND": "1",
                    "PTILOPSIS_CR_TELEGRAM_BOT_TOKEN": "legacy-token",
                    "PTILOPSIS_CR_TELEGRAM_CHAT_ID": "legacy-chat",
                }
            )

    def test_config_uses_canonical_transport_and_owner_options(self) -> None:
        config = build_cr_telegram_sink_config_from_env(
            self._env(
                TELEGRAM_API_BASE_URL="https://telegram.test/",
                TELEGRAM_TIMEOUT_SECONDS="7.5",
                TELEGRAM_OWNER_CHAT_IDS=" 11,22,11 ",
                PTILOPSIS_CR_TELEGRAM_PARSE_MODE="HTML",
                PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW="false",
            )
        )
        assert config is not None
        self.assertEqual(config.api_base_url, "https://telegram.test/")
        self.assertEqual(config.timeout_seconds, 7.5)
        self.assertEqual(config.parse_mode, "HTML")
        self.assertFalse(config.disable_web_page_preview)
        self.assertEqual(
            [target.chat_id for target in config.recipients.get_targets()],
            ["11", "22"],
        )
        self.assertNotIn(FAKE_TOKEN, repr(config))

    def test_subscription_store_is_opened_only_when_enabled(self) -> None:
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
            self.assertIsNotNone(config.recipients.store)

    def test_invalid_shared_timeout_and_cr_bool_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "TELEGRAM_TIMEOUT_SECONDS"
        ):
            build_cr_telegram_sink_config_from_env(
                self._env(TELEGRAM_TIMEOUT_SECONDS="nan")
            )
        with self.assertRaisesRegex(
            ValueError,
            "PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW",
        ):
            build_cr_telegram_sink_config_from_env(
                self._env(
                    PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW="maybe"
                )
            )

    def test_blank_parse_mode_becomes_none(self) -> None:
        config = build_cr_telegram_sink_config_from_env(
            self._env(PTILOPSIS_CR_TELEGRAM_PARSE_MODE="   ")
        )
        assert config is not None
        self.assertIsNone(config.parse_mode)

    def test_factory_preserves_injected_client_without_network(self) -> None:
        class SpyClient:
            called = False

            def post_json(self, *args: object, **kwargs: object) -> object:
                del args, kwargs
                self.called = True
                raise AssertionError("construction must not use the network")

        fake = SpyClient()
        sink = build_cr_telegram_sink_from_env(
            self._env(),
            http_client=fake,  # type: ignore[arg-type]
        )
        self.assertIsInstance(sink, CRTelegramSink)
        assert sink is not None
        self.assertIs(sink.http_client, fake)
        self.assertFalse(fake.called)


class TestCRTelegramEnvBoundaries(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_runtime_import_stays_lazy(self) -> None:
        source = (
            self.ROOT
            / "trendradar"
            / "application"
            / "services"
            / "cr_notification.py"
        ).read_text(encoding="utf-8")
        import_line = "from trendradar.cr.telegram_env import"
        self.assertIn(import_line, source)
        for line in source.splitlines():
            if line.strip().startswith(import_line):
                self.assertTrue(line.startswith(" "))

    def test_factory_does_not_import_product_or_storage_layers(self) -> None:
        source = (
            self.ROOT / "trendradar" / "cr" / "telegram_env.py"
        ).read_text(encoding="utf-8")
        for token in (
            "trendradar.notification",
            "trendradar.storage",
            "trendradar.config",
            "trendradar.ai",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
