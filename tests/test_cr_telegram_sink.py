# coding=utf-8
"""
PR9n: CR Telegram dispatch sink tests.

Covers:
  - config validation + frozen + token redaction
  - shared transport payload and endpoint integration
  - successful fake HTTP submission → accepted receipt
  - rejected (ok:false) / non-2xx HTTP → not-accepted, sanitized detail
  - transport exception propagation (sink + executor)
  - executor integration (order + message_index)
  - source boundary (no forbidden imports; runtime/__main__ don't import this)

All HTTP is via an injected FAKE client.  No real network calls.  Only fake
tokens are used.
"""

import dataclasses
import json
import os
import sys
import unittest
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.dispatch_executor import (
    CRDispatchReceipt,
    execute_cr_dispatch_plan,
)
from trendradar.cr.dispatch_plan import CRDispatchMessage, CRDispatchPlan
from trendradar.cr import (
    CRTelegramHTTPClient,
    CRTelegramHTTPResponse,
    CRUrllibTelegramHTTPClient,
)
from trendradar.cr.telegram_sink import (
    CRTelegramSink,
    CRTelegramSinkConfig,
)
from trendradar.telegram.fanout import RecipientTarget
from trendradar.telegram.recipients import ReaderRecipientProvider
from trendradar.telegram.transport import (
    TelegramHTTPClient,
    TelegramHTTPResponse,
    UrllibTelegramHTTPClient,
)


# Fake, obviously-not-real credentials used throughout.
FAKE_TOKEN = "FAKE-TOKEN-000:aaaabbbbcccc"
FAKE_CHAT = "fake-chat-42"


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class _FakeHTTPClient:
    """Records the last call and returns a canned response."""

    def __init__(self, response: TelegramHTTPResponse):
        self._response = response
        self.calls: list[dict] = []

    def post_json(self, url, payload, *, timeout_seconds):
        self.calls.append(
            {"url": url, "payload": payload, "timeout_seconds": timeout_seconds}
        )
        return self._response


class _RaisingHTTPClient:
    """HTTP client whose post_json always raises a transport error."""

    def post_json(self, url, payload, *, timeout_seconds):
        raise RuntimeError("transport boom")


def _ok_response() -> TelegramHTTPResponse:
    return TelegramHTTPResponse(
        status_code=200, body=json.dumps({"ok": True, "result": {"message_id": 7}})
    )


def _config(**overrides) -> CRTelegramSinkConfig:
    base = {
        "bot_token": FAKE_TOKEN,
        "recipients": ReaderRecipientProvider((FAKE_CHAT,)),
    }
    base.update(overrides)
    return CRTelegramSinkConfig(**base)


def _message(
    text: str = "CR-A alert body",
    candidate_count: int = 2,
    run_label: str = "2026-06-10 09:00",
) -> CRDispatchMessage:
    return CRDispatchMessage(
        text=text,
        format="plain_text",
        candidate_count=candidate_count,
        run_label=run_label,
        urgent_count=1,
        high_score_suppressed_count=0,
    )


def _ready_plan(messages: tuple[CRDispatchMessage, ...]) -> CRDispatchPlan:
    first = messages[0]
    return CRDispatchPlan(
        should_dispatch=True,
        messages=messages,
        reason="ready",
        run_label=first.run_label,
        candidate_count=first.candidate_count,
        urgent_count=first.urgent_count,
        high_score_suppressed_count=first.high_score_suppressed_count,
    )


# ---------------------------------------------------------------------------
# Group A — Config / model shape
# ---------------------------------------------------------------------------


class TestConfigShape(unittest.TestCase):
    def test_config_is_frozen(self):
        cfg = _config()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            cfg.recipients = ReaderRecipientProvider(("other",))  # type: ignore[misc]

    def test_rejects_empty_bot_token(self):
        with self.assertRaises(ValueError):
            _config(bot_token="")

    def test_rejects_non_positive_timeout(self):
        with self.assertRaises(ValueError):
            _config(timeout_seconds=0)
        with self.assertRaises(ValueError):
            _config(timeout_seconds=-1.0)

    def test_rejects_empty_api_base_url(self):
        with self.assertRaises(ValueError):
            _config(api_base_url="")

    def test_accepts_normal_config(self):
        cfg = _config()
        self.assertEqual(
            cfg.recipients.get_targets(),
            (RecipientTarget(FAKE_CHAT),),
        )
        self.assertEqual(cfg.api_base_url, "https://api.telegram.org")
        self.assertTrue(cfg.disable_web_page_preview)

    def test_token_not_in_repr(self):
        cfg = _config()
        self.assertNotIn(FAKE_TOKEN, repr(cfg))

    def test_http_response_is_frozen(self):
        resp = TelegramHTTPResponse(status_code=200, body="{}")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            resp.status_code = 500  # type: ignore[misc]

    def test_legacy_transport_exports_remain_compatible(self):
        self.assertIs(CRTelegramHTTPResponse, TelegramHTTPResponse)
        self.assertIs(
            CRUrllibTelegramHTTPClient,
            UrllibTelegramHTTPClient,
        )
        json_only_client = _FakeHTTPClient(_ok_response())
        self.assertIsInstance(json_only_client, CRTelegramHTTPClient)
        self.assertNotIsInstance(json_only_client, TelegramHTTPClient)


# ---------------------------------------------------------------------------
# Group B — Shared transport integration
# ---------------------------------------------------------------------------


class TestSharedTransportIntegration(unittest.TestCase):
    def test_sink_reuses_validated_transport_config(self):
        fake = _FakeHTTPClient(_ok_response())
        config = _config()
        sink = CRTelegramSink(config=config, http_client=fake)
        transport = sink.transport

        sink.submit(_message(), message_index=0)
        sink.submit(_message(), message_index=1)

        self.assertIs(sink.transport, transport)
        self.assertIs(transport.config, config.transport_config)
        self.assertEqual(len(fake.calls), 2)

    def test_token_never_in_receipt_detail(self):
        sink = CRTelegramSink(config=_config(), http_client=_FakeHTTPClient(_ok_response()))
        receipt = sink.submit(_message(), message_index=0)
        self.assertNotIn(FAKE_TOKEN, receipt.detail)
        # endpoint path must not leak either
        self.assertNotIn("sendMessage", receipt.detail)


# ---------------------------------------------------------------------------
# Group D — Successful fake HTTP submission
# ---------------------------------------------------------------------------


class TestSuccessfulSubmission(unittest.TestCase):
    def test_success_receipt(self):
        fake = _FakeHTTPClient(_ok_response())
        cfg = _config(timeout_seconds=7.5)
        sink = CRTelegramSink(config=cfg, http_client=fake)
        msg = _message(candidate_count=4, run_label="run-d")

        receipt = sink.submit(msg, message_index=0)

        self.assertIsInstance(receipt, CRDispatchReceipt)
        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.status, "accepted")
        self.assertEqual(
            receipt.detail,
            "recipients=1,text_ok=1,text_failed=0,"
            "document_ok=0,document_failed=0,blocked=0",
        )
        self.assertEqual(receipt.message_index, 0)
        self.assertEqual(receipt.candidate_count, 4)
        self.assertEqual(receipt.run_label, "run-d")

    def test_fake_client_records_url_payload_timeout(self):
        fake = _FakeHTTPClient(_ok_response())
        cfg = _config(
            api_base_url="https://api.telegram.org/",
            timeout_seconds=3.0,
            parse_mode="MarkdownV2",
            disable_web_page_preview=False,
        )
        sink = CRTelegramSink(config=cfg, http_client=fake)
        msg = _message(text="hello")

        sink.submit(msg, message_index=0)

        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        self.assertNotIn(".org//bot", call["url"])
        self.assertIn(f"/bot{FAKE_TOKEN}/sendMessage", call["url"])
        self.assertEqual(call["payload"]["text"], "hello")
        self.assertEqual(call["payload"]["chat_id"], FAKE_CHAT)
        self.assertEqual(call["payload"]["parse_mode"], "MarkdownV2")
        self.assertIs(call["payload"]["disable_web_page_preview"], False)
        self.assertEqual(call["timeout_seconds"], 3.0)


# ---------------------------------------------------------------------------
# Group E — Rejected / error responses
# ---------------------------------------------------------------------------


class TestRejectedResponses(unittest.TestCase):
    def test_ok_false_200_rejected(self):
        body = json.dumps(
            {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
        )
        fake = _FakeHTTPClient(TelegramHTTPResponse(status_code=200, body=body))
        sink = CRTelegramSink(config=_config(), http_client=fake)

        receipt = sink.submit(_message(), message_index=0)

        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.status, "rejected")
        self.assertIn("text_failed=1", receipt.detail)

    def test_http_400_rejected(self):
        body = json.dumps({"ok": False, "error_code": 400, "description": "Bad Request"})
        fake = _FakeHTTPClient(TelegramHTTPResponse(status_code=400, body=body))
        sink = CRTelegramSink(config=_config(), http_client=fake)

        receipt = sink.submit(_message(), message_index=0)

        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.status, "rejected")
        self.assertIn("text_failed=1", receipt.detail)

    def test_detail_has_no_token_or_chat_id(self):
        # Even if a (hypothetical) description echoed secrets, they are redacted.
        body = json.dumps(
            {"ok": False, "description": f"token {FAKE_TOKEN} chat {FAKE_CHAT}"}
        )
        fake = _FakeHTTPClient(TelegramHTTPResponse(status_code=200, body=body))
        sink = CRTelegramSink(config=_config(), http_client=fake)

        receipt = sink.submit(_message(), message_index=0)

        self.assertNotIn(FAKE_TOKEN, receipt.detail)
        self.assertNotIn(FAKE_CHAT, receipt.detail)

    def test_preserves_metadata_on_rejection(self):
        fake = _FakeHTTPClient(
            TelegramHTTPResponse(status_code=200, body=json.dumps({"ok": False}))
        )
        sink = CRTelegramSink(config=_config(), http_client=fake)
        msg = _message(candidate_count=9, run_label="run-e")
        receipt = sink.submit(msg, message_index=2)
        self.assertEqual(receipt.message_index, 2)
        self.assertEqual(receipt.candidate_count, 9)
        self.assertEqual(receipt.run_label, "run-e")

    def test_partial_fanout_accepts_and_attempts_later_recipients(self):
        class _SequenceClient:
            def __init__(self):
                self.calls = []
                self.responses = [
                    _ok_response(),
                    TelegramHTTPResponse(
                        status_code=500,
                        body=json.dumps({"ok": False}),
                    ),
                ]

            def post_json(self, url, payload, *, timeout_seconds):
                del url, timeout_seconds
                self.calls.append(payload["chat_id"])
                return self.responses.pop(0)

        config = _config(
            recipients=ReaderRecipientProvider(("owner", "subscriber")),
        )
        client = _SequenceClient()

        receipt = CRTelegramSink(config=config, http_client=client).submit(
            _message(),
            message_index=0,
        )

        self.assertEqual(client.calls, ["owner", "subscriber"])
        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.status, "accepted_partial")
        self.assertIn("recipients=2,text_ok=1,text_failed=1", receipt.detail)


# ---------------------------------------------------------------------------
# Group F — Transport exception behavior
# ---------------------------------------------------------------------------


class TestTransportExceptions(unittest.TestCase):
    def test_sink_propagates_transport_error(self):
        sink = CRTelegramSink(config=_config(), http_client=_RaisingHTTPClient())
        with self.assertRaises(RuntimeError):
            sink.submit(_message(), message_index=0)

    def test_executor_propagates_transport_error(self):
        sink = CRTelegramSink(config=_config(), http_client=_RaisingHTTPClient())
        plan = _ready_plan((_message(),))
        with self.assertRaises(RuntimeError):
            execute_cr_dispatch_plan(plan, sink=sink)


# ---------------------------------------------------------------------------
# Group G — Executor integration
# ---------------------------------------------------------------------------


class TestExecutorIntegration(unittest.TestCase):
    def test_single_message_via_executor(self):
        fake = _FakeHTTPClient(_ok_response())
        sink = CRTelegramSink(config=_config(), http_client=fake)
        plan = _ready_plan((_message(),))

        result = execute_cr_dispatch_plan(plan, sink=sink)

        self.assertTrue(result.attempted)
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(len(result.receipts), 1)

    def test_two_messages_preserve_order_and_index(self):
        class _RecordingClient:
            def __init__(self):
                self.calls = []

            def post_json(self, url, payload, *, timeout_seconds):
                self.calls.append(payload["text"])
                return _ok_response()

        client = _RecordingClient()
        sink = CRTelegramSink(config=_config(), http_client=client)
        m0 = _message(text="first")
        m1 = _message(text="second")
        plan = _ready_plan((m0, m1))

        result = execute_cr_dispatch_plan(plan, sink=sink)

        self.assertEqual(client.calls, ["first", "second"])
        self.assertEqual([r.message_index for r in result.receipts], [0, 1])
        self.assertEqual(result.accepted_count, 2)


# ---------------------------------------------------------------------------
# Group H — Boundary / source checks
# ---------------------------------------------------------------------------


class TestSourceBoundary(unittest.TestCase):
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

    FORBIDDEN = (
        "trendradar.notification",
        "trendradar.storage",
        "trendradar.config",
        "trendradar.ai",
        "AIAnalysisResult",
        "requests",
        "httpx",
        "aiohttp",
        "cooldown",
        "dedupe",
        "alert_state",
    )

    def _read(self, *parts) -> str:
        return (self.PROJECT_ROOT.joinpath(*parts)).read_text(encoding="utf-8")

    def test_telegram_sink_has_no_forbidden_tokens(self):
        source = self._read("trendradar", "cr", "telegram_sink.py")
        for token in self.FORBIDDEN:
            self.assertNotIn(
                token, source, f"forbidden token {token!r} present in module"
            )

    def test_runtime_dry_run_does_not_import_telegram_sink(self):
        source = self._read("trendradar", "cr", "runtime_dry_run.py")
        self.assertNotIn("telegram_sink", source)

    def test_main_does_not_import_telegram_sink(self):
        # PR9p: __main__ may reference the env factory name (which contains
        # the substring "telegram_sink"), but must never import the sink
        # module directly — sink construction goes through the PR9o env
        # factory only.
        source = self._read("trendradar", "__main__.py")
        self.assertNotIn("trendradar.cr.telegram_sink", source)
        self.assertNotIn("from trendradar.cr import telegram_sink", source)
        self.assertNotIn("CRTelegramSink(", source)

    def test_tests_use_only_fake_token(self):
        # This very test file must not contain a real-looking bot token.
        # Real Telegram tokens look like <digits>:<35 base64-ish chars>.
        import re

        source = self._read("tests", "test_cr_telegram_sink.py")
        real_token_pattern = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")
        self.assertIsNone(real_token_pattern.search(source))


if __name__ == "__main__":
    unittest.main()
