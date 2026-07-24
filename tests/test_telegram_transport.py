# coding=utf-8
"""Tests for the sole Telegram HTTP and fanout boundary."""

from __future__ import annotations

import unittest

from trendradar.telegram.transport import (
    TelegramHTTPResponse,
    TelegramTransport,
    TelegramTransportConfig,
    send_to_recipients,
    transport_config_from_env,
)


class FakeRecipients:
    def __init__(self, chat_ids):
        self.chat_ids = chat_ids
        self.blocked = []

    def get_chat_ids(self):
        return self.chat_ids

    def mark_blocked(self, chat_id):
        self.blocked.append(chat_id)


class FakeClient:
    def __init__(self):
        self.json_calls = []

    def post_json(self, url, payload, *, timeout_seconds):
        self.json_calls.append((url, payload, timeout_seconds))
        if payload.get("chat_id") == "403-user":
            return TelegramHTTPResponse(
                403,
                '{"ok":false,"description":"Forbidden"}',
            )
        return TelegramHTTPResponse(200, '{"ok":true,"result":[]}')

    def post_multipart(self, *args, **kwargs):
        return TelegramHTTPResponse(200, '{"ok":true}')


class TestTelegramTransport(unittest.TestCase):
    def _transport(self, fake):
        ticks = iter((0.0, 1.0, 2.0, 3.0, 4.0))
        return TelegramTransport(
            TelegramTransportConfig(bot_token="secret"),
            http_client=fake,
            monotonic=lambda: next(ticks),
            sleep=lambda _seconds: None,
        )

    def test_response_requires_http_success_and_ok_true(self):
        self.assertTrue(TelegramHTTPResponse(200, '{"ok":true}').ok)
        self.assertFalse(TelegramHTTPResponse(500, '{"ok":true}').ok)
        self.assertFalse(TelegramHTTPResponse(200, "not-json").ok)

    def test_canonical_env_config(self):
        config = transport_config_from_env(
            {
                "TELEGRAM_BOT_TOKEN": "secret",
                "TELEGRAM_API_BASE_URL": "https://example.test",
                "TELEGRAM_TIMEOUT_SECONDS": "12.5",
            }
        )
        self.assertEqual(config.api_base_url, "https://example.test")
        self.assertEqual(config.timeout_seconds, 12.5)
        self.assertNotIn("secret", repr(config))

    def test_send_message_builds_bot_api_payload(self):
        fake = FakeClient()
        response = self._transport(fake).send_message(
            chat_id="11",
            text="hello",
            parse_mode="HTML",
        )
        self.assertTrue(response.ok)
        url, payload, timeout = fake.json_calls[0]
        self.assertIn("/botsecret/sendMessage", url)
        self.assertEqual(payload["chat_id"], "11")
        self.assertEqual(payload["text"], "hello")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertEqual(timeout, 10.0)

    def test_get_updates_uses_offset_long_poll_and_message_allowlist(self):
        fake = FakeClient()
        self._transport(fake).get_updates(offset=42, timeout_seconds=50)
        _, payload, timeout = fake.json_calls[0]
        self.assertEqual(payload["offset"], 42)
        self.assertEqual(payload["timeout"], 50)
        self.assertEqual(payload["allowed_updates"], ["message"])
        self.assertEqual(timeout, 55.0)

    def test_fanout_deduplicates_and_marks_403_blocked(self):
        fake = FakeClient()
        recipients = FakeRecipients(["ok", "403-user", "ok"])
        summary = send_to_recipients(
            self._transport(fake),
            recipients,
            text="body",
            parse_mode=None,
            disable_web_page_preview=True,
        )
        self.assertEqual(summary.recipient_count, 2)
        self.assertEqual(summary.text_accepted_count, 1)
        self.assertEqual(summary.text_failed_count, 1)
        self.assertEqual(summary.blocked_count, 1)
        self.assertEqual(recipients.blocked, ["403-user"])
        self.assertNotIn("403-user", summary.detail())


if __name__ == "__main__":
    unittest.main()
