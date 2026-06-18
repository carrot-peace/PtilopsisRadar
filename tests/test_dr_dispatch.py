# coding=utf-8
"""Tests for the DR dispatch pipeline."""

from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.ai.analyzer import AIAnalysisResult
from trendradar.dr.dispatch_executor import (
    DRMemoryDispatchSink,
    execute_dr_dispatch_plan,
)
from trendradar.dr.dispatch_mode import (
    DR_DISPATCH_ARTIFACT,
    DR_DISPATCH_LIVE,
    DR_DISPATCH_OFF,
    resolve_dr_dispatch_mode,
)
from trendradar.dr.dispatch_plan import (
    DRDispatchMessage,
    build_dr_dispatch_plan,
)
from trendradar.dr.formatter import (
    DR_FALLBACK_TEXT,
    render_dr_telegram_text,
    select_dr_digest_topics,
)
from trendradar.dr.telegram_env import (
    build_dr_telegram_sink_config_from_env,
    build_dr_telegram_sink_from_env,
    dr_telegram_send_enabled,
)
from trendradar.dr.telegram_sink import (
    DRTelegramHTTPResponse,
    DRTelegramSink,
    build_telegram_send_document_fields,
    build_telegram_send_message_payload,
)


FAKE_TOKEN = "FAKE-DR-TOKEN-000:abc"
FAKE_CHAT = "fake-dr-chat"


def _ai_result(**overrides) -> AIAnalysisResult:
    result = AIAnalysisResult(
        report_style="environment",
        success=True,
        overview="今日 AI Brief 概览。",
        cross_layer_verified=[
            {
                "topic": "Topic A",
                "source_layers": "A/B",
                "highest_heat": "#1",
                "summary": "Topic A summary",
                "source_links": ["https://example.test/a"],
            }
        ],
        high_heat_unverified=[
            {
                "topic": "Topic B",
                "source_layers": "D",
                "highest_heat": "#2",
                "summary": "Topic B summary with https://example.test/link",
            }
        ],
        chinese_only_hot=[
            {
                "topic": "Topic A!",
                "source_layers": "D",
                "highest_heat": "#3",
                "summary": "Duplicate topic should be removed",
            }
        ],
    )
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


class TestDRFormatter(unittest.TestCase):
    def test_ai_overview_rendered(self) -> None:
        text = render_dr_telegram_text(_ai_result(), date="2026-06-18")
        self.assertIn("Ptilopsis Radar｜DR", text)
        self.assertIn("<b>AI Brief</b>", text)
        self.assertIn("今日 AI Brief 概览", text)

    def test_topics_selected_and_deduped(self) -> None:
        topics = select_dr_digest_topics(_ai_result())
        self.assertEqual([t["topic"] for t in topics], ["Topic A", "Topic B"])

    def test_no_ai_fallback(self) -> None:
        text = render_dr_telegram_text(None, date="2026-06-18")
        self.assertIn(DR_FALLBACK_TEXT, text)
        self.assertIn("DR HTML: attached", text)

    def test_failed_ai_fallback(self) -> None:
        failed = AIAnalysisResult(report_style="environment", success=False, error="x")
        text = render_dr_telegram_text(failed, date="2026-06-18")
        self.assertIn(DR_FALLBACK_TEXT, text)

    def test_text_omits_urls_and_decision(self) -> None:
        text = render_dr_telegram_text(_ai_result(), date="2026-06-18")
        self.assertNotIn("https://", text)
        self.assertNotIn("Decision", text)
        self.assertNotIn("source_links", text)


class TestDRPlanExecutor(unittest.TestCase):
    def test_missing_html_blocks_plan(self) -> None:
        plan = build_dr_dispatch_plan(
            text="body", html_path="", run_label="r", date="2026-06-18"
        )
        self.assertFalse(plan.should_dispatch)
        self.assertEqual(plan.reason, "missing_html")

    def test_empty_text_blocks_plan(self) -> None:
        plan = build_dr_dispatch_plan(
            text=" ", html_path="daily.html", run_label="r", date="2026-06-18"
        )
        self.assertFalse(plan.should_dispatch)
        self.assertEqual(plan.reason, "empty_text")

    def test_ready_plan(self) -> None:
        plan = build_dr_dispatch_plan(
            text="body", html_path="daily.html", run_label="r", date="2026-06-18"
        )
        self.assertTrue(plan.should_dispatch)
        self.assertEqual(plan.reason, "ready")
        self.assertEqual(plan.messages[0].format, "telegram_html")

    def test_frozen_message(self) -> None:
        msg = DRDispatchMessage(
            text="x", format="telegram_html", run_label="r",
            date="2026-06-18", html_path="daily.html",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            msg.text = "y"  # type: ignore[misc]

    def test_executor_artifact_mode_no_sink(self) -> None:
        plan = build_dr_dispatch_plan(
            text="body", html_path="daily.html", run_label="r", date="2026-06-18"
        )
        result = execute_dr_dispatch_plan(plan, sink=None)
        self.assertFalse(result.attempted)
        self.assertEqual(result.reason, "no_sink")

    def test_executor_memory_sink_accepts(self) -> None:
        plan = build_dr_dispatch_plan(
            text="body", html_path="daily.html", run_label="r", date="2026-06-18"
        )
        sink = DRMemoryDispatchSink()
        result = execute_dr_dispatch_plan(plan, sink=sink)
        self.assertTrue(result.attempted)
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(len(sink.submitted_messages), 1)

    def test_executor_transport_failure_receipt(self) -> None:
        class BadSink:
            def submit(self, message, *, message_index):
                raise TimeoutError("boom")

        plan = build_dr_dispatch_plan(
            text="body", html_path="daily.html", run_label="r", date="2026-06-18"
        )
        result = execute_dr_dispatch_plan(plan, sink=BadSink())
        self.assertEqual(result.receipts[0].status, "failed_transport")


class TestDREnvAndSink(unittest.TestCase):
    def _env(self, **overrides: str) -> dict[str, str]:
        env = {
            "PTILOPSIS_DR_TELEGRAM_SEND": "1",
            "PTILOPSIS_DR_TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
            "PTILOPSIS_DR_TELEGRAM_CHAT_ID": FAKE_CHAT,
        }
        env.update(overrides)
        return env

    def test_mode_default_off(self) -> None:
        self.assertEqual(resolve_dr_dispatch_mode({}), DR_DISPATCH_OFF)

    def test_modes(self) -> None:
        self.assertEqual(
            resolve_dr_dispatch_mode({"PTILOPSIS_DR_DISPATCH_MODE": "artifact"}),
            DR_DISPATCH_ARTIFACT,
        )
        self.assertEqual(
            resolve_dr_dispatch_mode({"PTILOPSIS_DR_DISPATCH_MODE": "live"}),
            DR_DISPATCH_LIVE,
        )

    def test_send_gate_exact_one(self) -> None:
        self.assertTrue(dr_telegram_send_enabled({"PTILOPSIS_DR_TELEGRAM_SEND": "1"}))
        self.assertFalse(dr_telegram_send_enabled({"PTILOPSIS_DR_TELEGRAM_SEND": " 1 "}))

    def test_missing_credentials_raise_when_enabled(self) -> None:
        env = self._env()
        del env["PTILOPSIS_DR_TELEGRAM_BOT_TOKEN"]
        with self.assertRaises(ValueError):
            build_dr_telegram_sink_config_from_env(env)

    def test_disabled_returns_none(self) -> None:
        self.assertIsNone(build_dr_telegram_sink_config_from_env({}))
        self.assertIsNone(build_dr_telegram_sink_from_env({}))

    def test_payload_builders(self) -> None:
        config = build_dr_telegram_sink_config_from_env(self._env())
        assert config is not None
        msg = DRDispatchMessage(
            text="body", format="telegram_html", run_label="r",
            date="2026-06-18", html_path="daily.html",
        )
        payload = build_telegram_send_message_payload(msg, config)
        self.assertEqual(payload["chat_id"], FAKE_CHAT)
        self.assertEqual(payload["parse_mode"], "HTML")
        fields = build_telegram_send_document_fields(msg, config)
        self.assertEqual(fields["caption"], "DR HTML")

    def test_sink_sends_text_and_document(self) -> None:
        class FakeClient:
            def __init__(self):
                self.json_payloads = []
                self.multipart_payloads = []

            def post_json(self, url, payload, *, timeout_seconds):
                self.json_payloads.append((url, payload))
                return DRTelegramHTTPResponse(200, '{"ok": true}')

            def post_multipart(
                self, url, *, fields, file_field, file_path, timeout_seconds
            ):
                self.multipart_payloads.append((url, fields, file_field, file_path))
                return DRTelegramHTTPResponse(200, '{"ok": true}')

        with tempfile.TemporaryDirectory() as td:
            html_path = Path(td) / "full.html"
            html_path.write_text("<html>DR</html>", encoding="utf-8")
            config = build_dr_telegram_sink_config_from_env(self._env())
            assert config is not None
            fake = FakeClient()
            sink = DRTelegramSink(config=config, http_client=fake)
            receipt = sink.submit(
                DRDispatchMessage(
                    text="body",
                    format="telegram_html",
                    run_label="r",
                    date="2026-06-18",
                    html_path=str(html_path),
                    attach_html=True,
                ),
                message_index=0,
            )
        self.assertTrue(receipt.accepted)
        self.assertTrue(receipt.text_accepted)
        self.assertTrue(receipt.document_accepted)
        self.assertEqual(len(fake.json_payloads), 1)
        self.assertEqual(len(fake.multipart_payloads), 1)

    def test_document_failure_keeps_text_accepted(self) -> None:
        class FakeClient:
            def post_json(self, url, payload, *, timeout_seconds):
                return DRTelegramHTTPResponse(200, '{"ok": true}')

            def post_multipart(
                self, url, *, fields, file_field, file_path, timeout_seconds
            ):
                return DRTelegramHTTPResponse(400, '{"ok": false}')

        with tempfile.TemporaryDirectory() as td:
            html_path = Path(td) / "full.html"
            html_path.write_text("<html>DR</html>", encoding="utf-8")
            config = build_dr_telegram_sink_config_from_env(self._env())
            assert config is not None
            receipt = DRTelegramSink(config=config, http_client=FakeClient()).submit(
                DRDispatchMessage(
                    text="body",
                    format="telegram_html",
                    run_label="r",
                    date="2026-06-18",
                    html_path=str(html_path),
                    attach_html=True,
                ),
                message_index=0,
            )
        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.status, "accepted_document_failed")
        self.assertFalse(receipt.document_accepted)


class TestDRSourceBoundaries(unittest.TestCase):
    def test_dr_modules_do_not_import_cr_telegram_or_notification(self) -> None:
        root = Path(__file__).resolve().parent.parent
        for path in (root / "trendradar" / "dr").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("trendradar.cr.telegram", text)
            self.assertNotIn("trendradar.notification", text)
            self.assertNotIn("send_to_telegram", text)
            self.assertNotIn("dispatch_all", text)

    def test_main_has_dr_hook_but_no_legacy_sender_call(self) -> None:
        root = Path(__file__).resolve().parent.parent
        text = (root / "trendradar" / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("_run_dr_dispatch_hook", text)
        self.assertNotIn("send_to_telegram(", text)
        self.assertNotIn("dispatch_all(", text)


if __name__ == "__main__":
    unittest.main()
