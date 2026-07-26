# coding=utf-8
"""Telegram reader fan-out primitive tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trendradar.telegram.fanout import (
    RecipientTarget,
    TelegramFanoutSummary,
    send_to_recipients,
)
from trendradar.telegram.transport import TelegramHTTPResponse


def _response(status: int = 200) -> TelegramHTTPResponse:
    ok = "true" if 200 <= status < 300 else "false"
    return TelegramHTTPResponse(status, f'{{"ok":{ok}}}')


class FakeProvider:
    def __init__(self, targets: list[RecipientTarget]) -> None:
        self.targets = targets
        self.blocked: list[RecipientTarget] = []

    def get_targets(self):
        return self.targets

    def mark_blocked(self, target):
        self.blocked.append(target)
        return True


class FakeTransport:
    def __init__(self) -> None:
        self.text_results: list[TelegramHTTPResponse | BaseException] = []
        self.document_results: list[TelegramHTTPResponse | BaseException] = []
        self.text_chat_ids: list[str] = []
        self.document_chat_ids: list[str] = []

    def send_message(self, *, chat_id, text, **kwargs):
        del text, kwargs
        self.text_chat_ids.append(chat_id)
        value = self.text_results.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def send_document(self, *, chat_id, file_path, caption, **kwargs):
        del file_path, caption, kwargs
        self.document_chat_ids.append(chat_id)
        value = self.document_results.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class TestTelegramFanout(unittest.TestCase):
    def test_deduplicates_targets_and_aggregates_partial_text_delivery(self) -> None:
        provider = FakeProvider(
            [
                RecipientTarget("1"),
                RecipientTarget("2", 7),
                RecipientTarget("1", 99),
            ]
        )
        transport = FakeTransport()
        transport.text_results = [_response(), _response(500)]

        summary = send_to_recipients(
            transport,  # type: ignore[arg-type]
            provider,
            text="reader message",
            parse_mode=None,
            disable_web_page_preview=True,
        )

        self.assertEqual(transport.text_chat_ids, ["1", "2"])
        self.assertTrue(summary.accepted)
        self.assertTrue(summary.partial)
        self.assertEqual(
            summary,
            TelegramFanoutSummary(2, 1, 1, 0, 0, 0),
        )
        self.assertEqual(
            summary.detail(),
            "recipients=2,text_ok=1,text_failed=1,"
            "document_ok=0,document_failed=0,blocked=0",
        )

    def test_403_reports_the_exact_versioned_target_as_blocked(self) -> None:
        target = RecipientTarget("20", 4)
        provider = FakeProvider([target])
        transport = FakeTransport()
        transport.text_results = [_response(403)]

        summary = send_to_recipients(
            transport,  # type: ignore[arg-type]
            provider,
            text="reader message",
            parse_mode=None,
            disable_web_page_preview=True,
        )

        self.assertEqual(provider.blocked, [target])
        self.assertEqual(summary.blocked_count, 1)
        self.assertFalse(summary.accepted)

    def test_transport_failure_does_not_abort_later_recipients(self) -> None:
        provider = FakeProvider(
            [RecipientTarget("1"), RecipientTarget("2")]
        )
        transport = FakeTransport()
        transport.text_results = [TimeoutError("secret"), _response()]

        summary = send_to_recipients(
            transport,  # type: ignore[arg-type]
            provider,
            text="reader message",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        self.assertEqual(transport.text_chat_ids, ["1", "2"])
        self.assertEqual(summary.text_accepted_count, 1)
        self.assertEqual(summary.text_failed_count, 1)

    def test_document_is_sent_only_after_text_acceptance(self) -> None:
        provider = FakeProvider(
            [RecipientTarget("1"), RecipientTarget("2")]
        )
        transport = FakeTransport()
        transport.text_results = [_response(), _response(500)]
        transport.document_results = [_response()]

        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "reader.html"
            document.write_text("<html></html>", encoding="utf-8")
            summary = send_to_recipients(
                transport,  # type: ignore[arg-type]
                provider,
                text="reader message",
                parse_mode="HTML",
                disable_web_page_preview=True,
                document_path=document,
                document_caption="Reader HTML",
            )

        self.assertEqual(transport.document_chat_ids, ["1"])
        self.assertEqual(summary.document_accepted_count, 1)
        self.assertEqual(summary.document_failed_count, 0)

    def test_missing_document_is_counted_per_text_success(self) -> None:
        provider = FakeProvider(
            [RecipientTarget("1"), RecipientTarget("2")]
        )
        transport = FakeTransport()
        transport.text_results = [_response(), _response()]

        summary = send_to_recipients(
            transport,  # type: ignore[arg-type]
            provider,
            text="reader message",
            parse_mode=None,
            disable_web_page_preview=True,
            document_path=Path("missing-reader.html"),
        )

        self.assertEqual(summary.document_failed_count, 2)
        self.assertEqual(transport.document_chat_ids, [])


if __name__ == "__main__":
    unittest.main()
