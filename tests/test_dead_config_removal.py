# coding=utf-8
"""Regression guards for the supported runtime configuration surface."""

from pathlib import Path
from types import SimpleNamespace
import unittest

from mcp_server.services.data_service import DataService
from mcp_server.utils.errors import InvalidParameterError
from mcp_server.utils.validators import validate_config_section
from trendradar.core.loader import load_config


ROOT = Path(__file__).resolve().parents[1]


class TestRuntimeConfigSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(str(ROOT / "config" / "config.yaml"))

    def test_dead_runtime_sections_are_not_loaded(self):
        for key in ("DISPLAY", "DISPLAY_MODE", "ALERT", "TELEGRAM_ATTACHMENTS"):
            with self.subTest(key=key):
                self.assertNotIn(key, self.config)

    def test_translation_scope_has_no_standalone_compatibility(self):
        self.assertNotIn("STANDALONE", self.config["AI_TRANSLATION"]["SCOPE"])

    def test_generic_delivery_keys_are_not_loaded(self):
        for key in (
            "ENABLE_NOTIFICATION",
            "MESSAGE_BATCH_SIZE",
            "MAX_ACCOUNTS_PER_CHANNEL",
            "FEISHU_WEBHOOK_URL",
            "DINGTALK_WEBHOOK_URL",
            "WEWORK_WEBHOOK_URL",
            "TELEGRAM_BOT_TOKEN",
            "EMAIL_FROM",
            "NTFY_TOPIC",
            "BARK_URL",
            "SLACK_WEBHOOK_URL",
            "GENERIC_WEBHOOK_URL",
        ):
            with self.subTest(key=key):
                self.assertNotIn(key, self.config)

    def test_classic_analysis_keys_are_not_loaded(self):
        analysis = self.config["AI_ANALYSIS"]
        for key in ("REPORT_STYLE", "PROMPT_FILE", "INCLUDE_STANDALONE"):
            with self.subTest(key=key):
                self.assertNotIn(key, analysis)


class TestAlertStateSurface(unittest.TestCase):
    def test_alert_state_module_and_storage_api_are_gone(self):
        self.assertFalse((ROOT / "trendradar" / "ai" / "alert_state.py").exists())
        for path in (
            "trendradar/storage/base.py",
            "trendradar/storage/local.py",
            "trendradar/storage/remote.py",
            "trendradar/storage/manager.py",
        ):
            source = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("def get_alert_state", source)
            self.assertNotIn("def save_alert_state", source)


class TestMCPConfigSurface(unittest.TestCase):
    def test_push_is_not_a_supported_config_section(self):
        with self.assertRaises(InvalidParameterError):
            validate_config_section("push")

    def test_all_config_has_no_push_section(self):
        service = DataService.__new__(DataService)
        service.parser = SimpleNamespace(
            parse_yaml_config=lambda: {
                "advanced": {
                    "crawler": {},
                    "weight": {},
                },
                "platforms": {"enabled": True, "sources": []},
            },
            parse_frequency_words=lambda: [],
        )

        result = service.get_current_config("all")

        self.assertEqual(set(result), {"crawler", "keywords", "weights"})


if __name__ == "__main__":
    unittest.main()
