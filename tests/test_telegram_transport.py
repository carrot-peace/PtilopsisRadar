# coding=utf-8
"""Tests for the shared low-level Telegram transport."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trendradar.deployment.operator_alert import (
    SharedTransportOperatorTelegramSender,
)
from trendradar.telegram.transport import (
    TelegramHTTPResponse,
    TelegramTransport,
    TelegramTransportConfig,
    UrllibTelegramHTTPClient,
    transport_config_from_env,
)


class FakeHTTPClient:
    def __init__(self, response=None):
        self.response = response or TelegramHTTPResponse(200, '{"ok": true}')
        self.calls = []

    def post_json(self, url, payload, *, timeout_seconds):
        self.calls.append((url, payload, timeout_seconds))
        return self.response

    def post_multipart(
        self,
        url,
        *,
        fields,
        file_field,
        file_path,
        timeout_seconds,
        content_type=None,
    ):
        self.calls.append(
            (
                url,
                fields,
                file_field,
                file_path,
                timeout_seconds,
                content_type,
            )
        )
        return self.response


class FalsyFakeHTTPClient(FakeHTTPClient):
    def __bool__(self):
        return False


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

    def test_falsy_injected_client_is_preserved(self):
        fake = FalsyFakeHTTPClient()
        transport = TelegramTransport(
            TelegramTransportConfig(bot_token="secret"),
            http_client=fake,
        )
        self.assertIs(transport.client, fake)
        transport.send_message(chat_id="11", text="diagnostic")
        self.assertEqual(len(fake.calls), 1)

    def test_default_http_client_is_reused(self):
        transport = TelegramTransport(
            TelegramTransportConfig(bot_token="secret")
        )
        self.assertIs(transport.client, transport.client)

    def test_response_requires_http_success_and_ok_true(self):
        self.assertTrue(TelegramHTTPResponse(200, '{"ok": true}').ok)
        self.assertFalse(TelegramHTTPResponse(500, '{"ok": true}').ok)
        self.assertFalse(TelegramHTTPResponse(200, "not-json").ok)

    def test_polling_config_payload_and_result(self):
        config = transport_config_from_env(
            {
                "TELEGRAM_BOT_TOKEN": "secret",
                "TELEGRAM_API_BASE_URL": "https://telegram.test/",
                "TELEGRAM_TIMEOUT_SECONDS": "7.5",
            }
        )
        fake = FakeHTTPClient(
            TelegramHTTPResponse(200, '{"ok":true,"result":[]}')
        )
        transport = TelegramTransport(config, http_client=fake)
        self.assertEqual(
            transport.get_updates(offset=42, timeout_seconds=50).result,
            [],
        )
        url, payload, timeout = fake.calls[0]
        self.assertEqual(url, "https://telegram.test/botsecret/getUpdates")
        self.assertEqual(payload["offset"], 42)
        self.assertEqual(payload["allowed_updates"], ["message"])
        self.assertEqual(timeout, 55.0)

        fake.response = TelegramHTTPResponse(
            200,
            '{"ok":true,"result":{"url":""}}',
        )
        self.assertEqual(transport.get_webhook_info().result, {"url": ""})
        self.assertTrue(fake.calls[1][0].endswith("/getWebhookInfo"))

    def test_polling_config_requires_token_and_numeric_timeout(self):
        with self.assertRaises(ValueError):
            transport_config_from_env({})
        with self.assertRaises(ValueError):
            transport_config_from_env(
                {
                    "TELEGRAM_BOT_TOKEN": "secret",
                    "TELEGRAM_TIMEOUT_SECONDS": "bad",
                }
            )

    def test_send_document_uses_shared_multipart_client(self):
        fake = FakeHTTPClient()
        transport = TelegramTransport(
            TelegramTransportConfig(bot_token="secret"),
            http_client=fake,
        )
        path = Path("daily.html")
        response = transport.send_document(
            chat_id="11",
            file_path=path,
            caption="DR HTML",
            content_type="text/html; charset=utf-8",
        )
        self.assertTrue(response.ok)
        url, fields, file_field, file_path, timeout, content_type = fake.calls[0]
        self.assertEqual(url, "https://api.telegram.org/botsecret/sendDocument")
        self.assertEqual(fields, {"chat_id": "11", "caption": "DR HTML"})
        self.assertEqual(file_field, "document")
        self.assertEqual(file_path, path)
        self.assertEqual(timeout, 10.0)
        self.assertEqual(content_type, "text/html; charset=utf-8")

    def test_multipart_content_type_override_is_written_to_request(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "daily"
            path.write_text("<html>DR</html>", encoding="utf-8")
            client = UrllibTelegramHTTPClient()
            response = TelegramHTTPResponse(200, '{"ok": true}')
            with patch.object(client, "_open", return_value=response) as opened:
                client.post_multipart(
                    "https://telegram.test/sendDocument",
                    fields={"chat_id": "11"},
                    file_field="document",
                    file_path=path,
                    timeout_seconds=10.0,
                    content_type="text/html; charset=utf-8",
                )
            request = opened.call_args.args[0]
            self.assertIn(
                b"Content-Type: text/html; charset=utf-8\r\n",
                request.data,
            )

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
