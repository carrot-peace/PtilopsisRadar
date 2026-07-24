# coding=utf-8
"""Tests for the shared low-level Telegram transport."""

from __future__ import annotations

import unittest

from trendradar.deployment.operator_alert import (
    SharedTransportOperatorTelegramSender,
)
from trendradar.telegram.transport import (
    TelegramHTTPResponse,
    TelegramTransport,
    TelegramTransportConfig,
)


class FakeHTTPClient:
    def __init__(self, response=None):
        self.response = response or TelegramHTTPResponse(200, '{"ok": true}')
        self.calls = []

    def post_json(self, url, payload, *, timeout_seconds):
        self.calls.append((url, payload, timeout_seconds))
        return self.response


class TestTelegramTransport(unittest.TestCase):
    def test_config_hides_token_and_validates_timeout(self):
        config = TelegramTransportConfig(bot_token="secret")
        self.assertNotIn("secret", repr(config))
        with self.assertRaises(ValueError):
            TelegramTransportConfig(bot_token="secret", timeout_seconds=0)

    def test_send_message_builds_the_existing_payload(self):
        fake = FakeHTTPClient()
        transport = TelegramTransport(
            TelegramTransportConfig(
                bot_token="secret",
                api_base_url="https://telegram.test/",
                timeout_seconds=7.5,
            ),
            http_client=fake,
        )
        response = transport.send_message(chat_id="11", text="diagnostic")
        self.assertTrue(response.ok)
        url, payload, timeout = fake.calls[0]
        self.assertEqual(url, "https://telegram.test/botsecret/sendMessage")
        self.assertEqual(
            payload,
            {
                "chat_id": "11",
                "text": "diagnostic",
                "disable_web_page_preview": True,
            },
        )
        self.assertEqual(timeout, 7.5)

    def test_response_requires_http_success_and_ok_true(self):
        self.assertTrue(TelegramHTTPResponse(200, '{"ok": true}').ok)
        self.assertFalse(TelegramHTTPResponse(500, '{"ok": true}').ok)
        self.assertFalse(TelegramHTTPResponse(200, "not-json").ok)

    def test_operator_adapter_uses_shared_transport_without_behavior_change(self):
        fake = FakeHTTPClient(TelegramHTTPResponse(400, '{"ok": false}'))
        result = SharedTransportOperatorTelegramSender(fake).send(
            bot_token="secret",
            chat_id="11",
            text="diagnostic",
            api_base_url="https://telegram.test",
            timeout_seconds=10,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "telegram_http_400")


if __name__ == "__main__":
    unittest.main()
