# coding=utf-8
"""CR adapter tests against the shared Telegram boundary."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trendradar.cr.dispatch_plan import CRDispatchMessage
from trendradar.cr.telegram_sink import CRTelegramSink, CRTelegramSinkConfig
from trendradar.telegram.transport import (
    StaticRecipientProvider,
    TelegramHTTPResponse,
)


class FakeClient:
    def __init__(self, *, rejected_chat_ids=(), reject_documents=False):
        self.rejected_chat_ids = set(rejected_chat_ids)
        self.reject_documents = reject_documents
        self.json_calls = []
        self.multipart_calls = []

    def post_json(self, url, payload, *, timeout_seconds):
        self.json_calls.append((url, payload, timeout_seconds))
        if str(payload["chat_id"]) in self.rejected_chat_ids:
            return TelegramHTTPResponse(403, '{"ok": false}')
        return TelegramHTTPResponse(200, '{"ok": true}')

    def post_multipart(
        self, url, *, fields, file_field, file_path, timeout_seconds
    ):
        self.multipart_calls.append((url, fields, file_field, file_path))
        if self.reject_documents:
            return TelegramHTTPResponse(400, '{"ok": false}')
        return TelegramHTTPResponse(200, '{"ok": true}')


def _message(html_path: str = "") -> CRDispatchMessage:
    return CRDispatchMessage(
        text="CR body",
        format="plain_text",
        candidate_count=2,
        run_label="run-1",
        urgent_count=1,
        high_score_suppressed_count=0,
        html_path=html_path,
    )


class TestCRTelegramSink(unittest.TestCase):
    def _config(self, recipients=("11", "22"), **overrides):
        values = {
            "bot_token": "fake-token",
            "recipients": StaticRecipientProvider(tuple(recipients)),
        }
        values.update(overrides)
        return CRTelegramSinkConfig(**values)

    def test_token_and_recipients_are_absent_from_repr(self):
        config = self._config()
        rendered = repr(config)
        self.assertNotIn("fake-token", rendered)
        self.assertNotIn("11", rendered)

    def test_fanout_acceptance_is_aggregated_without_chat_ids(self):
        fake = FakeClient(rejected_chat_ids={"22"})
        receipt = CRTelegramSink(self._config(), http_client=fake).submit(
            _message(),
            message_index=0,
        )
        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.status, "accepted_partial")
        self.assertEqual(receipt.recipient_count, 2)
        self.assertEqual(receipt.text_accepted_count, 1)
        self.assertEqual(receipt.text_failed_count, 1)
        self.assertEqual(receipt.blocked_count, 1)
        self.assertNotIn("11", receipt.detail)
        self.assertNotIn("22", receipt.detail)

    def test_all_text_failures_reject_the_message(self):
        fake = FakeClient(rejected_chat_ids={"11", "22"})
        receipt = CRTelegramSink(self._config(), http_client=fake).submit(
            _message(),
            message_index=0,
        )
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.status, "rejected")
        self.assertEqual(receipt.text_failed_count, 2)

    def test_html_is_sent_after_text_to_each_successful_recipient(self):
        with tempfile.TemporaryDirectory() as directory:
            html = Path(directory) / "cr.html"
            html.write_text("<html>CR</html>", encoding="utf-8")
            fake = FakeClient()
            receipt = CRTelegramSink(
                self._config(), http_client=fake
            ).submit(_message(str(html)), message_index=0)
        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.document_accepted_count, 2)
        self.assertEqual(len(fake.json_calls), 2)
        self.assertEqual(len(fake.multipart_calls), 2)

    def test_document_failure_keeps_text_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            html = Path(directory) / "cr.html"
            html.write_text("<html>CR</html>", encoding="utf-8")
            receipt = CRTelegramSink(
                self._config(recipients=("11",)),
                http_client=FakeClient(reject_documents=True),
            ).submit(_message(str(html)), message_index=0)
        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.status, "accepted_partial")
        self.assertEqual(receipt.document_failed_count, 1)

    def test_missing_document_is_partial_not_text_failure(self):
        receipt = CRTelegramSink(
            self._config(recipients=("11",)),
            http_client=FakeClient(),
        ).submit(_message("/missing/cr.html"), message_index=0)
        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.document_failed_count, 1)


if __name__ == "__main__":
    unittest.main()
